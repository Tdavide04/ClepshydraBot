import asyncio
from io import BytesIO
import discord
import aiohttp
import urllib.parse

from utils.arena_overrides import get_override_rarity
from utils.card_cache import (
    get_cached_card,
    set_cached_card,
    is_artisan_legal_stale,
    mark_artisan_legal,
)
from utils.deck_image_generator import DeckImageGenerator
from cogs.deck_validation.models import DeckEntry, DeckValidationResult, ArtisanCard
from cogs.deck_validation.validators import check_banlist
from database import get_session
from repositories.banlist_repository import BanlistRepository


_COLLECTION_URL = "https://api.scryfall.com/cards/collection"

SCRYFALL_UNAVAILABLE_MESSAGE = (
    "⚠️ Scryfall, il servizio usato per verificare le carte, non risponde in questo momento: "
    "il mazzo non è stato valutato. Riprova tra qualche minuto."
)
_COLLECTION_CHUNK = 75
_MIN_REQUEST_INTERVAL = 0.11

_SCRYFALL_SEMAPHORE = asyncio.Semaphore(1)
_ARENA_LEGAL_CACHE: dict[str, bool] = {}


class ScryfallUnavailable(Exception):
    """Scryfall gave no usable answer (network error, timeout, 5xx or 429
    past the retries, any other unexpected status). Deliberately distinct
    from 404, which on /cards/search is a valid answer ("no printings
    found") and makes the card illegal: until 3.5.6 both became None, and a
    plain timeout stored the card as illegal in _ARENA_LEGAL_CACHE until the
    bot restarted."""

# Module-level banlist cache: the bot creates two separate ArtisanService
# instances (tournament_system and deck_validation), which must see the same
# banlist, explicit invalidations after add/remove included. A per-instance
# self._banlist attribute (as before) left stale the instance not used by the
# command that made the change.
_banlist_cache: set[str] | None = None


def invalidate_banlist_cache() -> None:
    """Forces the banlist to be reloaded from the DB on the next validation."""
    global _banlist_cache
    _banlist_cache = None


def _expand_double_faced(names: set[str]) -> set[str]:
    """Adds the front half alone for every double-faced card ("front //
    back") already in the set.

    cards.txt (and therefore banned_cards) stores double-faced cards with the
    full name, but parse_decklist() truncates to the front face when reading
    the user's deck (mimicking MTG Arena's export format) - without this
    expansion, check_banlist() (exact set comparison) never matches these
    cards, so they are never caught as banned.

    Used only to build the ArtisanService._load_banlist() cache, NOT inside
    BanlistRepository.get_all_for_format(): that method also feeds /banlist
    (a public command), which must list only the cards actually stored in the
    DB, not derived synthetic variants.
    """
    expanded = set(names)
    for name in names:
        if " // " in name:
            expanded.add(name.split(" // ")[0].strip())
    return expanded


class ArtisanService:

    def __init__(self, bot=None):
        self.bot = bot
        self._logger = None

    def _get_logger(self):
        if self._logger is None and self.bot:
            self._logger = self.bot.get_cog("Logger")
        return self._logger

    async def _load_banlist(self) -> set[str]:
        global _banlist_cache
        session = get_session()
        if session is None:
            return _banlist_cache or set()
        try:
            repo = BanlistRepository(session)
            raw = await repo.get_all_for_format()
            _banlist_cache = _expand_double_faced(raw)
            return _banlist_cache
        finally:
            await session.close()

    async def reload_banlist(self) -> set[str]:
        """Invalidates the module cache and reloads the banlist from the DB
        right away.

        Called by /banlist_aggiungi and /banlist_rimuovi: since the cache is
        shared at module level, the effect is immediately visible to the
        other ArtisanService instance too (cogs/deck_validation).
        """
        invalidate_banlist_cache()
        return await self._load_banlist()

    async def validate_deck(
        self,
        entries: list[DeckEntry],
        deck_name: str,
        total_cards: int,
    ) -> DeckValidationResult:
        if _banlist_cache is None:
            await self._load_banlist()

        banned = check_banlist(entries, _banlist_cache or set())
        if banned:
            return DeckValidationResult(
                deck_name=deck_name,
                total_cards=total_cards,
                main_count=sum(e.quantity for e in entries if not e.is_sideboard),
                side_count=sum(e.quantity for e in entries if e.is_sideboard),
                banned_cards=banned,
            )

        try:
            return await self._validate_with_scryfall(entries, deck_name, total_cards)
        except ScryfallUnavailable as e:
            # No card marked as not found or illegal: the deck simply wasn't
            # evaluated, and must be retried.
            return DeckValidationResult(
                deck_name=deck_name,
                total_cards=total_cards,
                main_count=sum(e.quantity for e in entries if not e.is_sideboard),
                side_count=sum(e.quantity for e in entries if e.is_sideboard),
                service_error=str(e),
            )

    async def _validate_with_scryfall(
        self,
        entries: list[DeckEntry],
        deck_name: str,
        total_cards: int,
    ) -> DeckValidationResult:
        headers = {"User-Agent": "ClepshydraBot/2.0 (Discord Tournament Bot)"}
        timeout = aiohttp.ClientTimeout(total=120)
        connector = aiohttp.TCPConnector(limit=2)

        unique_names = list({e.name for e in entries})

        async with aiohttp.ClientSession(
            headers=headers, timeout=timeout, connector=connector
        ) as session:
            card_map = await self._fetch_collection(session, unique_names)

            invalid_cards: list[str] = []
            illegal_rarity: list[str] = []
            mainboard: list[ArtisanCard] = []
            sideboard: list[ArtisanCard] = []

            for entry in entries:
                data = card_map.get(entry.name)
                if data is None:
                    for k, v in card_map.items():
                        if k.lower() == entry.name.lower():
                            data = v
                            break

                if data is None:
                    invalid_cards.append(entry.name)
                    continue

                legal = await self._is_arena_artisan_legal(session, data, entry.name)
                if not legal:
                    illegal_rarity.append(entry.name)

                image_url = self._extract_image_url(data)
                if not image_url:
                    continue

                card_obj = ArtisanCard(
                    name=entry.name,
                    quantity=entry.quantity,
                    image_url=image_url,
                    type_line=data.get("type_line", ""),
                    cmc=data.get("cmc", 0),
                    is_sideboard=entry.is_sideboard,
                )

                if entry.is_sideboard:
                    sideboard.append(card_obj)
                else:
                    mainboard.append(card_obj)

            main_count = sum(e.quantity for e in entries if not e.is_sideboard)
            side_count = sum(e.quantity for e in entries if e.is_sideboard)

            return DeckValidationResult(
                deck_name=deck_name,
                total_cards=total_cards,
                main_count=main_count,
                side_count=side_count,
                invalid_cards=invalid_cards,
                illegal_rarity_cards=illegal_rarity,
                mainboard=mainboard,
                sideboard=sideboard,
            )

    async def validate_and_publish(
        self,
        interaction,
        entries: list[DeckEntry],
        deck_name: str,
        total_cards: int
    ):
        member = interaction.user
        logger = self._get_logger()

        result = await self.validate_deck(entries, deck_name, total_cards)

        if result.service_error:
            await interaction.edit_original_response(content=SCRYFALL_UNAVAILABLE_MESSAGE)
            if logger:
                await logger.send_log(
                    level="WARN",
                    event="SCRYFALL_UNAVAILABLE",
                    user=member,
                    info=f"/artisan_check_deck: deck not evaluated ({result.service_error})",
                )
            return result

        deck_image = None
        if result.is_valid:
            mainboard_dicts = [c.to_dict() for c in result.mainboard]
            sideboard_dicts = [c.to_dict() for c in result.sideboard]
            async with aiohttp.ClientSession() as session:
                deck_image = await DeckImageGenerator.create_deck_showcase(
                    session, mainboard_dicts, sideboard_dicts,
                    player_name=member.display_name,
                    deck_name=deck_name
                )

        await self._publish_result(interaction, result, deck_image, logger, member)
        return result

    async def generate_deck_image(
        self,
        result: DeckValidationResult,
        player_name: str,
    ) -> BytesIO | None:
        if not result.is_valid:
            return None
        async with aiohttp.ClientSession() as session:
            return await DeckImageGenerator.create_deck_showcase(
                session,
                [c.to_dict() for c in result.mainboard],
                [c.to_dict() for c in result.sideboard],
                player_name=player_name,
                deck_name=result.deck_name,
            )

    async def _publish_result(
        self,
        interaction,
        result: DeckValidationResult,
        deck_image,
        logger,
        member
    ):
        from cogs.deck_validation.embeds import build_result_embed
        from config.config import LOG_CHANNEL_ID, PUBLIC_DECK_CHANNEL_ID

        embed = build_result_embed(result, member)

        published = False
        for channel_id in [LOG_CHANNEL_ID, PUBLIC_DECK_CHANNEL_ID]:
            try:
                channel = await interaction.client.fetch_channel(channel_id)
                if deck_image:
                    deck_image.seek(0)
                    file = discord.File(deck_image, filename="deck.png")
                    embed.set_image(url="attachment://deck.png")
                    await channel.send(embed=embed, file=file)
                else:
                    await channel.send(embed=embed)
                published = True
            except discord.Forbidden:
                if logger:
                    await logger.send_log(
                        level="ERROR",
                        event="PUBLISH_FORBIDDEN",
                        info=f"No access to channel {channel_id}"
                    )
            except Exception:
                import traceback
                traceback.print_exc()

        await interaction.edit_original_response(
            content="Analisi completata e pubblicata!" if published
            else "Analisi completata ma non e stato possibile pubblicare il risultato."
        )

        if logger:
            logger_info = (
                f"Outcome: {'OK' if result.is_valid else 'INVALID'}\n"
                f"Cards: {result.total_cards}"
            )
            await logger.send_log(
                level="INFO" if result.is_valid else "WARN",
                event="TOURNAMENT_DECK_CHECK",
                user=member,
                info=logger_info
            )

    async def _fetch_collection(
        self,
        session: aiohttp.ClientSession,
        names: list[str]
    ) -> dict[str, dict]:
        result: dict[str, dict] = {}
        to_fetch: list[str] = []

        for name in names:
            cached = get_cached_card(name)
            if cached is not None and "image_uris" in cached:
                result[name] = cached
            elif cached is not None and "card_faces" in cached and any("image_uris" in f for f in cached.get("card_faces", [])):
                result[name] = cached
            else:
                to_fetch.append(name)

        chunks = [
            to_fetch[i: i + _COLLECTION_CHUNK]
            for i in range(0, len(to_fetch), _COLLECTION_CHUNK)
        ]

        for idx, chunk in enumerate(chunks):
            payload = {"identifiers": [{"name": n} for n in chunk]}
            label = f"collection {idx + 1}/{len(chunks)} ({len(chunk)} cards)"
            data = await self._post_with_retry(session, _COLLECTION_URL, payload, label)

            for card in data.get("data", []):
                official = card.get("name", "")
                set_cached_card(official, card)
                result[official] = card
                if " // " in official:
                    front = official.split(" // ")[0].strip()
                    set_cached_card(front, card)
                    result[front] = card

        return result

    async def _is_arena_artisan_legal(
        self,
        session: aiohttp.ClientSession,
        card_data: dict,
        card_name: str
    ) -> bool:
        override = get_override_rarity(card_name)
        if override in ("common", "uncommon"):
            return True

        cached_entry = get_cached_card(card_name)
        if cached_entry is not None and "artisan_legal" in cached_entry:
            fresh = not is_artisan_legal_stale(cached_entry)
            if fresh and (cached_entry["artisan_legal"] or card_name.startswith("A-")):
                return cached_entry["artisan_legal"]

        oracle_id = card_data.get("oracle_id", "")
        if oracle_id and oracle_id in _ARENA_LEGAL_CACHE:
            return _ARENA_LEGAL_CACHE[oracle_id]

        prints_uri = card_data.get("prints_search_uri")
        if not prints_uri:
            return False

        arena_uri = self._arena_prints_uri(prints_uri)
        # A 404 (no Arena printings) arrives here as {"data": []} and makes
        # the card illegal, correctly stored below. A Scryfall failure instead
        # raises ScryfallUnavailable and leaves the caches untouched.
        prints_data = await self._get_with_retry(session, arena_uri, f"{card_name} [prints]")

        legal = False
        for printing in prints_data.get("data", []):
            rarity = printing.get("rarity", "").lower()
            set_type = printing.get("set_type", "").lower()
            if set_type == "alchemy" and printing.get("name", "").startswith("A-"):
                continue
            if rarity in ("common", "uncommon"):
                legal = True
                break

        if cached_entry is not None:
            mark_artisan_legal(card_name, cached_entry, legal)

        if oracle_id:
            _ARENA_LEGAL_CACHE[oracle_id] = legal

        return legal

    async def _post_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        payload: dict,
        label: str,
        retries: int = 5
    ) -> dict:
        return await self._request_with_retry(session, "POST", url, label, retries, payload)

    async def _get_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        label: str,
        retries: int = 5
    ) -> dict:
        return await self._request_with_retry(session, "GET", url, label, retries)

    async def _request_with_retry(
        self,
        session: aiohttp.ClientSession,
        method: str,
        url: str,
        label: str,
        retries: int,
        payload: dict | None = None,
    ) -> dict:
        """Scryfall request serialized by the semaphore, with retries on 429,
        5xx and network errors. Returns the response JSON; a 404 becomes
        {"data": []} (on /cards/search it means "no results", the only
        endpoint where it happens - /cards/collection reports missing cards in
        `not_found` with status 200). Any other outcome raises
        ScryfallUnavailable instead of returning None."""

        last_problem = "no attempt made"
        async with _SCRYFALL_SEMAPHORE:
            for attempt in range(retries):
                try:
                    async with session.request(method, url, json=payload) as resp:
                        if resp.status == 429:
                            last_problem = "HTTP 429"
                            await asyncio.sleep(float(resp.headers.get("Retry-After", 2 ** attempt)))
                            continue
                        if resp.status >= 500:
                            last_problem = f"HTTP {resp.status}"
                            await asyncio.sleep(2 ** attempt)
                            continue
                        if resp.status == 404:
                            await asyncio.sleep(_MIN_REQUEST_INTERVAL)
                            return {"data": []}
                        if resp.status != 200:
                            raise ScryfallUnavailable(f"{label}: HTTP {resp.status}")
                        data = await resp.json()
                        await asyncio.sleep(_MIN_REQUEST_INTERVAL)
                        return data
                except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                    last_problem = type(e).__name__
                    await asyncio.sleep(2 ** attempt)

        raise ScryfallUnavailable(f"{label}: {last_problem} after {retries} attempts")

    def _arena_prints_uri(self, prints_search_uri: str) -> str:
        parsed = urllib.parse.urlparse(prints_search_uri)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        q = params.get("q", [""])[0]
        params["q"] = [q + " game:arena"]
        new_query = urllib.parse.urlencode({k: v[0] for k, v in params.items()})
        return urllib.parse.urlunparse(parsed._replace(query=new_query))

    def _extract_image_url(self, card_data: dict) -> str | None:
        if "image_uris" in card_data:
            return card_data["image_uris"].get("small")
        elif "card_faces" in card_data:
            for face in card_data["card_faces"]:
                if "image_uris" in face:
                    url = face["image_uris"].get("small")
                    if url:
                        return url
                url = face.get("image_url")
                if url:
                    return url
        url = card_data.get("image_url")
        if url:
            return url
        return None
