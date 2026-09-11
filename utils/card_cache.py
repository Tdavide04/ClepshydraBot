import json
import os
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

CACHE_PATH = "data/card_cache.json"

# Dopo quanti giorni un flag artisan_legal cacheato va ri-verificato via Scryfall
# invece di essere considerato definitivo. Copre il caso di una carta ristampata
# su Arena con una rarita' diversa dopo il primo check (vedi mark_artisan_legal /
# is_artisan_legal_stale). Le entry cacheate prima dell'introduzione del TTL non
# hanno il campo checked_at: vengono trattate come scadute (fail-open verso un
# ricontrollo), non come valide a tempo indeterminato.
ARTISAN_LEGAL_TTL_DAYS = 30

_card_cache: dict = {}
_dirty = False
_save_lock = asyncio.Lock()


def load_cache():
    global _card_cache

    if _card_cache:
        return

    if not os.path.exists(CACHE_PATH):
        _card_cache = {}
        return

    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            _card_cache = json.load(f)
    except Exception:
        _card_cache = {}


async def save_cache():
    global _dirty

    async with _save_lock:

        if not _dirty:
            return

        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)

        temp_path = CACHE_PATH + ".tmp"

        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(_card_cache, f, indent=2, ensure_ascii=False)

        os.replace(temp_path, CACHE_PATH)

        _dirty = False


def get_cached_card(card_name: str) -> Optional[dict]:
    return _card_cache.get(card_name.lower())


def set_cached_card(card_name: str, data: dict):
    global _dirty

    _card_cache[card_name.lower()] = data
    _dirty = True


def is_artisan_legal_stale(entry: dict) -> bool:
    """True se il flag artisan_legal manca il timestamp o ha superato il TTL."""
    checked_at = entry.get("artisan_legal_checked_at")
    if not checked_at:
        return True
    try:
        checked = datetime.fromisoformat(checked_at)
    except ValueError:
        return True
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - checked > timedelta(days=ARTISAN_LEGAL_TTL_DAYS)


def mark_artisan_legal(card_name: str, entry: dict, legal: bool) -> None:
    """Imposta artisan_legal + il timestamp del check e salva la entry in cache."""
    entry["artisan_legal"] = legal
    entry["artisan_legal_checked_at"] = datetime.now(timezone.utc).isoformat()
    set_cached_card(card_name, entry)


def invalidate_card(card_name: str) -> bool:
    """Rimuove una carta dalla cache: forza un fetch Scryfall completo (dati +
    legalita' Artisan) alla prossima validazione. Restituisce True se la carta
    era presente."""
    global _dirty

    key = card_name.lower()
    if key in _card_cache:
        del _card_cache[key]
        _dirty = True
        return True
    return False


async def periodic_save_loop():
    while True:
        await asyncio.sleep(60)
        await save_cache()