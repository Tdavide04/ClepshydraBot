import asyncio
import aiohttp
import discord
import re
import os
import urllib.parse

from discord.ext import commands
from datetime import datetime
from dotenv import load_dotenv

from utils.arena_overrides import get_override_rarity
from utils.deck_image_generator import DeckImageGenerator
from utils.card_cache import load_cache, get_cached_card, set_cached_card, save_cache

load_dotenv()

LOG_GUILD_ID = int(os.getenv("LOG_GUILD_ID"))
PUBLIC_DECK_CHANNEL_ID = int(os.getenv("PUBLIC_DECK_CHANNEL_ID"))

# ============================================================
# Strategia richieste Scryfall
# ============================================================

_ARENA_LEGAL_CACHE: dict[str, bool] = {}
_SCRYFALL_SEMAPHORE = asyncio.Semaphore(1)
_MIN_REQUEST_INTERVAL = 0.11
_COLLECTION_URL = "https://api.scryfall.com/cards/collection"
_COLLECTION_CHUNK = 75

# ============================================================
# Banlist
# ============================================================

BANLIST_PATH = "cards.txt"

def _load_banlist(path: str = BANLIST_PATH) -> set[str]:
    banned: set[str] = set()
    if not os.path.exists(path):
        return banned
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if not name:
                continue
            banned.add(name.lower())
            if " // " in name:
                banned.add(name.split(" // ")[0].strip().lower())
    return banned

_BANLIST: set[str] = _load_banlist()


# ============================================================
# HTTP helpers
# ============================================================

async def _post_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    payload: dict,
    label: str,
    retries: int = 5
) -> dict | None:

    async with _SCRYFALL_SEMAPHORE:
        for attempt in range(retries):
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 429:
                        wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                        await asyncio.sleep(wait)
                        continue
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    await asyncio.sleep(_MIN_REQUEST_INTERVAL)
                    return data
            except asyncio.TimeoutError:
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                return None
        return None


async def _get_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    label: str,
    retries: int = 5
) -> dict | None:

    async with _SCRYFALL_SEMAPHORE:
        for attempt in range(retries):
            try:
                async with session.get(url) as resp:
                    if resp.status == 429:
                        wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                        await asyncio.sleep(wait)
                        continue
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    await asyncio.sleep(_MIN_REQUEST_INTERVAL)
                    return data
            except asyncio.TimeoutError:
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                return None
        return None


def _arena_prints_uri(prints_search_uri: str) -> str:
    parsed = urllib.parse.urlparse(prints_search_uri)
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    q = params.get("q", [""])[0]
    params["q"] = [q + " game:arena"]
    new_query = urllib.parse.urlencode({k: v[0] for k, v in params.items()})
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


# ============================================================
# Scryfall fetch helpers
# ============================================================

async def fetch_collection(
    session: aiohttp.ClientSession,
    names: list[str]
) -> dict[str, dict]:

    result: dict[str, dict] = {}

    to_fetch = []
    for name in names:
        cached = get_cached_card(name)
        if cached is not None:
            result[name] = cached
        else:
            to_fetch.append(name)

    chunks = [
        to_fetch[i: i + _COLLECTION_CHUNK]
        for i in range(0, len(to_fetch), _COLLECTION_CHUNK)
    ]

    for idx, chunk in enumerate(chunks):
        payload = {"identifiers": [{"name": n} for n in chunk]}
        label = f"collection {idx + 1}/{len(chunks)} ({len(chunk)} carte)"
        data = await _post_with_retry(session, _COLLECTION_URL, payload, label)
        if not data:
            continue

        not_found = [x.get("name", "?") for x in data.get("not_found", [])]

        for card in data.get("data", []):
            official = card.get("name", "")
            set_cached_card(official, card)
            result[official] = card
            if " // " in official:
                front = official.split(" // ")[0].strip()
                set_cached_card(front, card)
                result[front] = card

    return result


async def is_arena_artisan_legal(
    session: aiohttp.ClientSession,
    card_data: dict,
    card_name: str
) -> bool:

    override = get_override_rarity(card_name)
    if override in ("common", "uncommon"):
        return True

    cached_entry = get_cached_card(card_name)
    if cached_entry is not None and "artisan_legal" in cached_entry:
        cached_legal = cached_entry["artisan_legal"]
        return cached_legal

    oracle_id = card_data.get("oracle_id", "")
    if oracle_id and oracle_id in _ARENA_LEGAL_CACHE:
        cached = _ARENA_LEGAL_CACHE[oracle_id]
        return cached

    prints_uri = card_data.get("prints_search_uri")
    if not prints_uri:
        return False

    arena_uri = _arena_prints_uri(prints_uri)
    prints_data = await _get_with_retry(session, arena_uri, f"{card_name} [prints]")

    if not prints_data:
        if oracle_id:
            _ARENA_LEGAL_CACHE[oracle_id] = False
        return False

    legal = False
    for printing in prints_data.get("data", []):
        rarity = printing.get("rarity", "").lower()
        set_name = printing.get("set_name", "?")
        set_type = printing.get("set_type", "").lower()

        if set_type == "alchemy":
            continue

        if rarity in ("common", "uncommon"):
            legal = True
            break

    if cached_entry is not None:
        cached_entry["artisan_legal"] = legal
        set_cached_card(card_name, cached_entry)

    if oracle_id:
        _ARENA_LEGAL_CACHE[oracle_id] = legal

    return legal


# ============================================================
# Modal
# ============================================================

class ArtisanDeckCheckModal(
    discord.ui.Modal,
    title="Controllo Mazzo Artisan"
):

    deck_list = discord.ui.TextInput(
        label="Incolla la tua lista (60 Main + 15 Side)",
        style=discord.TextStyle.paragraph,
        placeholder=(
            "Deck\n"
            "4 Experimental Confectioner (WOE) 314\n"
            "Sideboard\n"
            "3 Pawpatch Formation (BLB) 186"
        ),
        required=True,
        min_length=10
    )

    def _parse_decklist(
        self, raw: str
    ) -> tuple[list[tuple[int, str, bool]], int, str]:

        pattern = r"^(\d+)\s+(.+)"
        entries: list[tuple[int, str, bool]] = []
        totale = 0
        in_side = False
        deck_name = "ARTISAN DECK"

        lines = raw.strip().split("\n")
        i = 0

        if lines and lines[0].strip().lower() == "about":
            i += 1
            if i < len(lines) and lines[i].strip():
                deck_name = lines[i].strip()
                i += 1

        for riga in lines[i:]:
            riga = riga.strip()
            if not riga or riga.lower() == "deck":
                continue
            if riga.lower() == "sideboard":
                in_side = True
                continue

            m = re.match(pattern, riga)
            if not m:
                continue

            qta = int(m.group(1))
            raw_nome = m.group(2).strip()
            raw_nome = re.sub(r"\s+\([A-Z0-9]+\)\s+\d+$", "", raw_nome).strip()
            nome = (
                raw_nome
                .replace("\u2019", "'")
                .replace("\u201c", '"')
                .replace("\u201d", '"')
            )

            if " // " in nome:
                nome = nome.split(" // ")[0].strip()

            entries.append((qta, nome, in_side))
            totale += qta

        return entries, totale, deck_name

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ):
        import traceback
        traceback.print_exception(type(error), error, error.__traceback__)
        try:
            await interaction.followup.send(
                "⚠️ Errore interno durante l'analisi.", ephemeral=True
            )
        except Exception:
            pass

    async def on_submit(self, interaction: discord.Interaction):

        await interaction.response.send_message(
            "🔍 Analisi del mazzo Artisan in corso...", ephemeral=True
        )

        member = interaction.user
        logger = interaction.client.get_cog("Logger")

        entries, totale_carte, deck_name = self._parse_decklist(self.deck_list.value)
        unique_names = list({nome for _, nome, _ in entries})

        headers = {"User-Agent": "ClepshydraBot/2.0 (Discord Tournament Bot)"}
        timeout = aiohttp.ClientTimeout(total=120)
        connector = aiohttp.TCPConnector(limit=2)

        carte_bannate: list[str] = []
        carte_invalide: list[str] = []
        rarita_non_artisan: list[str] = []
        mainboard: list[dict] = []
        sideboard: list[dict] = []

        # ── BANLIST (prima di qualsiasi richiesta Scryfall) ──
        for _, nome, _ in entries:
            if nome.lower() in _BANLIST and nome not in carte_bannate:
                carte_bannate.append(nome)

        if not carte_bannate:
            async with aiohttp.ClientSession(
                headers=headers, timeout=timeout, connector=connector
            ) as session:

                card_map = await fetch_collection(session, unique_names)
                for qta, nome, in_side in entries:
                    data = card_map.get(nome)
                    if data is None:
                        nl = nome.lower()
                        for k, v in card_map.items():
                            if k.lower() == nl:
                                data = v
                                break

                    if data is None:
                        carte_invalide.append(nome)
                        continue

                    legal = await is_arena_artisan_legal(session, data, nome)
                    if not legal:
                        rarita_non_artisan.append(nome)

                    image_url = None
                    if "image_uris" in data:
                        image_url = data["image_uris"].get("small")
                    elif "card_faces" in data:
                        for face in data["card_faces"]:
                            image_url = face.get("image_uris", {}).get("small")
                            if image_url:
                                break

                    if not image_url:
                        continue

                    card_obj = {
                        "name": nome,
                        "quantity": qta,
                        "image_url": image_url,
                        "type_line": data.get("type_line", ""),
                        "cmc": data.get("cmc", 0),
                    }

                    if in_side:
                        sideboard.append(card_obj)
                    else:
                        mainboard.append(card_obj)

        main_count = sum(qta for qta, _, in_side in entries if not in_side)
        side_count = sum(qta for qta, _, in_side in entries if in_side)

        esito = (
            not carte_bannate
            and not carte_invalide
            and not rarita_non_artisan
            and main_count >= 60
            and side_count <= 15
        )

        deck_image = None
        if esito:
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                deck_image = await DeckImageGenerator.create_deck_showcase(
                    session, mainboard, sideboard,
                    player_name=member.display_name,
                    deck_name=deck_name
                )

        # Embed
        color = discord.Color.green() if esito else discord.Color.red()
        embed = discord.Embed(
            title=f"⚔️ Artisan Deck Check: {member.display_name}",
            description="✅ Mazzo valido per Artisan" if esito else "❌ Mazzo NON valido per Artisan",
            color=color,
            timestamp=datetime.now()
        )

        if carte_bannate:
            embed.add_field(
                name="🚫 Carte Bannate",
                value="\n".join(carte_bannate[:10]),
                inline=False
            )

        if rarita_non_artisan:
            embed.add_field(
                name="❌ Non Artisan Legal",
                value="\n".join(rarita_non_artisan[:10]),
                inline=False
            )

        if carte_invalide:
            embed.add_field(
                name="⚠️ Carte non trovate",
                value="\n".join(carte_invalide[:10]),
                inline=False
            )

        resoconto = (
            f"📊 **Carte totali:** {totale_carte}\n"
            f"🃏 **Mainboard:** {main_count}/60\n"
            f"📦 **Sideboard:** {side_count}/15"
        )
        if carte_bannate:
            resoconto += f"\n🚫 **Bannate:** {len(carte_bannate)}"
        if rarita_non_artisan:
            resoconto += f"\n🚫 **Illegali:** {len(rarita_non_artisan)}"

        embed.add_field(name="Resoconto", value=resoconto, inline=False)

        try:
            channels_ids = [
                LOG_GUILD_ID,
                PUBLIC_DECK_CHANNEL_ID
            ]

            for channel_id in channels_ids:

                channel = await interaction.client.fetch_channel(channel_id)

                if deck_image:
                    deck_image.seek(0)

                    file = discord.File(deck_image, filename="deck.png")

                    embed.set_image(url="attachment://deck.png")

                    await channel.send(embed=embed, file=file)
                else:
                    await channel.send(embed=embed)
            await interaction.edit_original_response(content="✅ Analisi completata e pubblicata!")
        except Exception:
            import traceback
            traceback.print_exc()
            await interaction.edit_original_response(
                content="⚠️ Analisi completata ma si è verificato un errore."
            )

        if logger:
            await logger.send_log(
                level="INFO" if esito else "WARN",
                event="TOURNAMENT_DECK_CHECK",
                user=member,
                info=f"Esito: {'OK' if esito else 'NON VALIDO'}\nCarte: {totale_carte}"
            )


# ============================================================
# Cog
# ============================================================

class Tournament(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        load_cache()

    @discord.app_commands.command(
        name="artisan_check_deck",
        description="Analizza se il tuo deck è legale per Artisan Arena"
    )
    async def artisan_check_deck(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ArtisanDeckCheckModal())


async def setup(bot):
    await bot.add_cog(Tournament(bot))