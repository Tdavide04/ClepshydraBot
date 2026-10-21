"""
arena_overrides.py

Manages rarity overrides for cards that appear on Arena at a higher rarity
than their paper printings (e.g. SPG).

BUGS FIXED (September 2026, see CHANGELOG 1.9.0 and 3.0.0):
- update_spg_overrides used processed_sets to mark a whole set as "done
  forever" after the first successful scan. Wrong for SPG: Scryfall uses a
  single set code "SPG" that keeps growing over time (new Special Guests ship
  with almost every main set, every 4-8 weeks) - after the first scan, every
  later run (manual ones included) became a permanent no-op, with no way to
  unblock it short of editing the JSON by hand. Replaced by checked_cards: a
  per-set-code list of the individual cards already evaluated (override added
  or not). A new scan skips only the cards already seen, not the whole set -
  runs after the first one cost only the cards that are new since the last
  check, which makes scheduling them periodically safe (see
  periodic_spg_refresh_loop).
- _update_lock: the function now runs both from a manual admin command and
  from an automatic periodic task - a lock keeps two concurrent scans from
  overwriting each other's JSON.

BATCHING (September 2026): update_spg_overrides made one prints_search_uri
request for EVERY card not evaluated yet (N+1 pattern). Harmless for
incremental runs (a few new cards a week), but the first run after the
processed_sets -> checked_cards migration has to re-check the whole set at
once (hundreds of cards) - observed in production: dozens of consecutive
429s, every scan slowed down by exponential backoff. Replaced by
_fetch_prints_by_oracle_ids: one combined query (`oracleid:X or oracleid:Y
or ...`) per group of _PRINTS_BATCH_SIZE cards, returning all printings of
several cards in a single call (paginated if needed).
"""

import asyncio
import json
import os
from urllib.parse import quote

import aiohttp

from utils.sitemap_monitor import save_json_state

DATA_PATH = "data/arena_rarity_data.json"

_MIN_REQUEST_INTERVAL = 0.11

# How many cards per combined query in _fetch_prints_by_oracle_ids. Higher
# means fewer requests but a longer query (and more result pages to download,
# being the sum of the printings of every card in the batch); 25 is a cautious
# compromise, well under URL length limits and without risking huge
# multi-page responses for a single batch.
_PRINTS_BATCH_SIZE = 25

# New Special Guests ship with almost every main set (~4-8 weeks on average,
# see docs/caching.md). Weekly leaves a wide
# margin: after the first run, a check costs only the cards that are new since
# the last run (thanks to checked_cards), so even when nothing ever changes an
# empty run costs next to nothing.
_SPG_REFRESH_INTERVAL_SECONDS = 7 * 24 * 60 * 60

_override_cache: dict | None = None
_update_lock = asyncio.Lock()


# ==========================================
# LOAD / SAVE
# ==========================================


def _load_override_data() -> dict:
    """Loads the JSON. Uses an in-memory cache, rereads only when needed."""

    global _override_cache

    if _override_cache is not None:
        return _override_cache

    if not os.path.exists(DATA_PATH):
        _override_cache = {
            "overrides": {},
            "checked_cards": {},
        }
        return _override_cache

    with open(DATA_PATH, encoding="utf-8") as f:
        _override_cache = json.load(f)

    return _override_cache


def _save_override_data(data: dict) -> None:
    """Saves the JSON and updates the in-memory cache. The write is atomic: the file is curated data, and a
    failure mid-write used to leave it truncated (fixed in 3.6.6)."""

    global _override_cache

    save_json_state(DATA_PATH, data)

    _override_cache = data


def invalidate_override_cache() -> None:
    """Forces the JSON to be reloaded on the next read."""

    global _override_cache
    _override_cache = None


# ==========================================
# GET OVERRIDE (public API)
# ==========================================


def get_override_rarity(card_name: str) -> str | None:
    """
    Returns the override rarity for a card, or None if there is none.
    Uses the in-memory cache: no disk read on repeated calls.
    """

    data = _load_override_data()
    return data.get("overrides", {}).get(card_name)


# ==========================================
# SCRYFALL HELPER
# ==========================================


async def _scryfall_get(
    session: aiohttp.ClientSession, url: str, label: str, retries: int = 5
) -> dict | None:
    """
    GET to Scryfall with exponential backoff on 429.
    Same rate-limit policy as cogs/deck_validation/service.py.
    """

    for attempt in range(retries):
        try:
            async with session.get(url) as response:
                if response.status == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait_time = float(retry_after) if retry_after else 2**attempt

                    print(f"[429] {label} -> retry in {wait_time:.1f}s (attempt {attempt + 1}/{retries})")

                    await asyncio.sleep(wait_time)
                    continue

                if response.status != 200:
                    print(f"[SCRYFALL FAIL] {label} -> {response.status}")
                    return None

                data = await response.json()

                # Minimum delay after every 200 response
                await asyncio.sleep(_MIN_REQUEST_INTERVAL)

                return data

        except TimeoutError:
            print(f"[TIMEOUT] {label} (attempt {attempt + 1}/{retries})")
            await asyncio.sleep(2**attempt)

        except Exception as e:
            print(f"[SCRYFALL ERROR] {label}: {e}")
            return None

    print(f"[EXHAUSTED] {label}: all retries failed")
    return None


# ==========================================
# BATCH PRINTS FETCH
# ==========================================


async def _fetch_prints_by_oracle_ids(
    session: aiohttp.ClientSession,
    oracle_ids: list[str],
) -> dict[str, list[dict]]:
    """Fetches ALL printings of several cards in a single combined query
    (`oracleid:X or oracleid:Y or ...`, paginated if the group yields more
    than one page), instead of one prints_search_uri per card. Returns
    {oracle_id: [printing, ...]}; an oracle_id missing from the dict or with
    an empty list means the query failed for the whole batch (the caller must
    treat it as 'retry later', not as 'no printings')."""

    if not oracle_ids:
        return {}

    # Deduplicating is required, not just an optimization: verified live that
    # a query with repeated oracleids (`oracleid:X or oracleid:X`, which always
    # happens - the upstream 'set:spg unique=prints' search lists one row per
    # printing, so a card with several SPG printings appears more than once)
    # makes Scryfall return INCOMPLETE results (some cards silently missing)
    # instead of an explicit error.
    unique_oracle_ids = list(dict.fromkeys(oracle_ids))

    query = " or ".join(f"oracleid:{oid}" for oid in unique_oracle_ids)
    search_url: str | None = f"https://api.scryfall.com/cards/search?q={quote(query)}&unique=prints"

    grouped: dict[str, list[dict]] = {}

    while search_url:
        result = await _scryfall_get(session, search_url, f"prints batch ({len(oracle_ids)} cards)")

        if not result:
            # Batch failed: no card in the group is marked as checked, they
            # are all retried together on the next run.
            return {}

        for printing in result.get("data", []):
            oid = printing.get("oracle_id")
            if oid:
                grouped.setdefault(oid, []).append(printing)

        search_url = result.get("next_page")

    return grouped


# ==========================================
# UPDATE SPG OVERRIDES
# ==========================================


async def update_spg_overrides(set_code: str = "spg") -> list[tuple[str, str]]:
    """
    Scans the cards of the given set NOT EVALUATED YET on Scryfall and adds
    overrides for those that are rare/mythic on Arena but exist on paper as
    common/uncommon.

    Incremental by design: every evaluated card (override added or not) is
    recorded in checked_cards[set_code] and never downloaded again on later
    runs. Safe to call repeatedly (from an admin command or a periodic task):
    the first run on a set pays the full cost, later ones only the cards that
    appeared in the meantime. Printings of unevaluated cards are fetched in
    batches (_fetch_prints_by_oracle_ids, groups of _PRINTS_BATCH_SIZE), not
    one request per card.

    Returns the list of (card_name, rarity) added in THIS run (not the whole
    history).
    """

    async with _update_lock:
        set_upper = set_code.upper()

        data = _load_override_data()
        overrides: dict[str, str] = data.get("overrides", {})
        checked_by_set: dict[str, list[str]] = data.get("checked_cards", {})
        checked: set[str] = set(checked_by_set.get(set_upper, []))

        added_cards: list[tuple[str, str]] = []
        newly_checked: list[str] = []

        def _persist() -> None:
            checked_by_set[set_upper] = sorted(checked | set(newly_checked))
            _save_override_data(
                {
                    "overrides": overrides,
                    "checked_cards": checked_by_set,
                }
            )

        encoded_set = set_code.lower()
        search_url: str | None = f"https://api.scryfall.com/cards/search?q=set%3A{encoded_set}&unique=prints"

        headers = {"User-Agent": "ClepshydraBot/1.0 (Discord Tournament Bot)"}

        timeout = aiohttp.ClientTimeout(total=120)

        rarity_rank = {"common": 0, "uncommon": 1, "rare": 2, "mythic": 3}

        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            # 1. List every card in the set (name + oracle_id), paginating.
            unchecked: list[tuple[str, str | None]] = []

            while search_url:
                result = await _scryfall_get(session, search_url, f"search {set_upper}")

                if not result:
                    print(f"[ABORT] Could not fetch data for {set_upper}")
                    _persist()
                    return added_cards

                for card in result.get("data", []):
                    card_name: str = card.get("name", "")
                    if card_name and card_name not in checked:
                        unchecked.append((card_name, card.get("oracle_id")))

                search_url = result.get("next_page")

            print(f"[{set_upper}] {len(unchecked)} cards to evaluate")

            # 2. Fetch the printings of the unevaluated cards in batches.
            oracle_ids = [oid for _, oid in unchecked if oid]
            prints_by_oracle: dict[str, list[dict]] = {}

            for batch_start in range(0, len(oracle_ids), _PRINTS_BATCH_SIZE):
                batch = oracle_ids[batch_start : batch_start + _PRINTS_BATCH_SIZE]
                print(f"[BATCH] {batch_start + 1}-{batch_start + len(batch)} of {len(oracle_ids)}")
                prints_by_oracle.update(await _fetch_prints_by_oracle_ids(session, batch))

            # 3. Evaluate each card with the printings fetched in step 2.
            for card_name, oracle_id in unchecked:
                printings = prints_by_oracle.get(oracle_id) if oracle_id else None

                if not printings:
                    # No printings fetched (missing oracle_id or failed
                    # batch): don't mark it as checked, so it is retried on
                    # the next run instead of being lost forever.
                    continue

                arena_target_rarity: str | None = None
                paper_lowest: str | None = None

                for printing in printings:
                    games: list = printing.get("games", [])
                    rarity: str = printing.get("rarity", "").lower()
                    printing_set: str = printing.get("set", "").lower()

                    if "arena" in games and printing_set == set_code.lower():
                        arena_target_rarity = rarity

                    if "paper" in games and rarity in rarity_rank:
                        if paper_lowest is None or rarity_rank[rarity] < rarity_rank[paper_lowest]:
                            paper_lowest = rarity

                            if paper_lowest == "common":
                                break

                if (
                    arena_target_rarity in ("rare", "mythic")
                    and paper_lowest in ("common", "uncommon")
                    and card_name not in overrides
                ):
                    print(f"[OVERRIDE ADDED] {card_name} -> {paper_lowest} (Arena: {arena_target_rarity})")

                    overrides[card_name] = paper_lowest
                    added_cards.append((card_name, paper_lowest))

                newly_checked.append(card_name)

        _persist()

        print(
            f"[DONE] {set_upper}: "
            f"{len(added_cards)} new overrides, "
            f"{len(newly_checked)} cards checked in this run."
        )

        return added_cards


async def periodic_spg_refresh_loop(bot=None, interval_seconds: int = _SPG_REFRESH_INTERVAL_SECONDS) -> None:
    """Background task: re-checks the SPG set at regular intervals without an
    admin running the manual command. The first run starts right at startup
    (it doesn't wait for the first interval) so any new cards are picked up as
    soon as the bot restarts, not only once a week."""
    while True:
        try:
            added = await update_spg_overrides(set_code="spg")
            if added and bot is not None:
                logger = bot.get_cog("Logger")
                if logger:
                    lines = "\n".join(f"• **{name}** → {rarity}" for name, rarity in added[:20])
                    await logger.send_log(
                        level="INFO",
                        event="SPG_OVERRIDES_UPDATED",
                        info=f"Automatic check: {len(added)} new overrides found\n\n{lines}",
                    )
        except Exception as e:
            print(f"[SPG AUTO-REFRESH] error: {e}")

        await asyncio.sleep(interval_seconds)
