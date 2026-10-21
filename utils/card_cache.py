import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

from utils.console import log

# Path of the legacy JSON: used only for the one-off migration to SQLite
# (see load_cache()). Once migrated, the bot never reads or writes it again.
CACHE_PATH = "data/card_cache.json"

# After how many days a cached artisan_legal flag must be re-checked against
# Scryfall instead of being treated as final. Covers a card reprinted on Arena
# at a different rarity after the first check (see mark_artisan_legal /
# is_artisan_legal_stale). Entries cached before the TTL existed have no
# checked_at field: they count as stale (fail-open toward a re-check), not as
# valid forever.
ARTISAN_LEGAL_TTL_DAYS = 30

_card_cache: dict = {}
_loaded = False
# Names (lowercase key) to write/remove in SQLite on the next save_cache().
# Replaces the old boolean _dirty flag: instead of rewriting the whole cache on
# every save, save_cache() only updates the entries that changed.
_dirty_upserts: set[str] = set()
_dirty_deletes: set[str] = set()
_save_lock = asyncio.Lock()


async def load_cache() -> None:
    """Loads the cache from SQLite into _card_cache. Called once only, from
    database/engine.py:init_db(), after the engine and session are ready -
    not from every ArtisanService.__init__() as before (loading is a bot
    startup concern, not a per-service-instance one).

    If the table is empty and data/card_cache.json still exists (legacy data
    from before this change), imports the JSON into SQLite once.
    """
    global _card_cache, _loaded

    if _loaded:
        return

    from sqlalchemy import select

    from database import get_session
    from database.models import CachedCard

    session = get_session()
    if session is None:
        # init_db() not done yet: nothing to do here, init_db() itself calls
        # load_cache() again once the session is ready.
        return

    try:
        result = await session.execute(select(CachedCard))
        rows = result.scalars().all()

        # Blocking os.path call is fine here: load_cache() runs once at startup, before the bot serves
        # interactions.
        if not rows and os.path.exists(CACHE_PATH):  # noqa: ASYNC240
            legacy = _load_legacy_json()
            for name, entry in legacy.items():
                session.add(CachedCard(card_name=name, data=json.dumps(entry, ensure_ascii=False)))
            if legacy:
                await session.commit()
                print(f"Card cache: migrated {len(legacy)} entries from {CACHE_PATH} to SQLite")
            _card_cache = legacy
        else:
            _card_cache = {row.card_name: json.loads(row.data) for row in rows}

        _loaded = True
    finally:
        await session.close()


def _load_legacy_json() -> dict:
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


async def save_cache() -> None:
    """Writes to SQLite only the entries added/changed or removed since the
    last save (targeted UPSERT/DELETE), not the whole cache."""
    global _dirty_upserts, _dirty_deletes

    async with _save_lock:
        if not _dirty_upserts and not _dirty_deletes:
            return

        from database import get_session
        from database.models import CachedCard

        session = get_session()
        if session is None:
            return

        upserts = list(_dirty_upserts)
        deletes = list(_dirty_deletes)
        try:
            for name in upserts:
                entry = _card_cache.get(name)
                if entry is None:
                    continue
                payload = json.dumps(entry, ensure_ascii=False)
                existing = await session.get(CachedCard, name)
                if existing is None:
                    session.add(CachedCard(card_name=name, data=payload))
                else:
                    existing.data = payload

            for name in deletes:
                existing = await session.get(CachedCard, name)
                if existing is not None:
                    await session.delete(existing)

            await session.commit()
            _dirty_upserts.difference_update(upserts)
            _dirty_deletes.difference_update(deletes)
        finally:
            await session.close()


def get_cached_card(card_name: str) -> dict | None:
    return _card_cache.get(card_name.lower())


def set_cached_card(card_name: str, data: dict):
    key = card_name.lower()
    _card_cache[key] = data
    _dirty_upserts.add(key)
    _dirty_deletes.discard(key)


def is_artisan_legal_stale(entry: dict) -> bool:
    """True if the artisan_legal flag has no timestamp or is past the TTL."""
    checked_at = entry.get("artisan_legal_checked_at")
    if not checked_at:
        return True
    try:
        checked = datetime.fromisoformat(checked_at)
    except ValueError:
        return True
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=UTC)
    return datetime.now(UTC) - checked > timedelta(days=ARTISAN_LEGAL_TTL_DAYS)


def mark_artisan_legal(card_name: str, entry: dict, legal: bool) -> None:
    """Sets artisan_legal + the check timestamp and stores the entry in the cache."""
    entry["artisan_legal"] = legal
    entry["artisan_legal_checked_at"] = datetime.now(UTC).isoformat()
    set_cached_card(card_name, entry)


def invalidate_card(card_name: str) -> bool:
    """Removes a card from the cache: forces a full Scryfall fetch (data +
    Artisan legality) on the next validation. Returns True if the card was
    present."""
    key = card_name.lower()
    existed = key in _card_cache
    if existed:
        del _card_cache[key]
    _dirty_upserts.discard(key)
    _dirty_deletes.add(key)
    return existed


_SAVE_INTERVAL_SECONDS = 60


async def periodic_save_loop(interval_seconds: int = _SAVE_INTERVAL_SECONDS):
    """Saves the cache every minute. A failure (e.g. a locked DB) must not
    stop the loop: it used to be unhandled and silently killed the task,
    leaving the cache unsaved until restart. save_cache() clears
    _dirty_upserts/_dirty_deletes only after a successful commit, so the next
    run retries the same changes."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await save_cache()
        except Exception as e:
            log(f"[CARD CACHE] save failed, retrying in {interval_seconds}s: {type(e).__name__}: {e}")
