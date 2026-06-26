import json
import os
import asyncio
from typing import Optional

CACHE_PATH = "data/card_cache.json"

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


async def periodic_save_loop():
    while True:
        await asyncio.sleep(60)
        await save_cache()