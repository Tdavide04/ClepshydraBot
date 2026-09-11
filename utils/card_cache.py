import json
import os
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

# Path del JSON legacy: usato solo per la migrazione una tantum verso SQLite
# (vedi load_cache()). Una volta migrato, questo file non viene piu' letto ne'
# scritto dal bot.
CACHE_PATH = "data/card_cache.json"

# Dopo quanti giorni un flag artisan_legal cacheato va ri-verificato via Scryfall
# invece di essere considerato definitivo. Copre il caso di una carta ristampata
# su Arena con una rarita' diversa dopo il primo check (vedi mark_artisan_legal /
# is_artisan_legal_stale). Le entry cacheate prima dell'introduzione del TTL non
# hanno il campo checked_at: vengono trattate come scadute (fail-open verso un
# ricontrollo), non come valide a tempo indeterminato.
ARTISAN_LEGAL_TTL_DAYS = 30

_card_cache: dict = {}
_loaded = False
# Nomi (chiave lowercase) da scrivere/rimuovere su SQLite al prossimo save_cache().
# Sostituisce il vecchio flag booleano _dirty: invece di riscrivere l'intera
# cache ad ogni salvataggio, save_cache() aggiorna solo le entry cambiate.
_dirty_upserts: set[str] = set()
_dirty_deletes: set[str] = set()
_save_lock = asyncio.Lock()


async def load_cache() -> None:
    """Carica la cache da SQLite in _card_cache. Chiamata una volta sola da
    database/engine.py:init_db(), dopo che l'engine e la sessione sono pronti —
    non da ogni ArtisanService.__init__() come in precedenza (il caricamento e'
    un concern di avvio del bot, non di istanza del service).

    Se la tabella e' vuota e data/card_cache.json esiste ancora (dato legacy
    da prima di questa modifica), importa il JSON in SQLite una tantum.
    """
    global _card_cache, _loaded

    if _loaded:
        return

    from database import get_session
    from database.models import CachedCard
    from sqlalchemy import select

    session = get_session()
    if session is None:
        # init_db() non ancora completato: niente da fare qui, load_cache()
        # verra' richiamata da init_db() stesso a sessione pronta.
        return

    try:
        result = await session.execute(select(CachedCard))
        rows = result.scalars().all()

        if not rows and os.path.exists(CACHE_PATH):
            legacy = _load_legacy_json()
            for name, entry in legacy.items():
                session.add(CachedCard(card_name=name, data=json.dumps(entry, ensure_ascii=False)))
            if legacy:
                await session.commit()
                print(f"Cache carte: migrate {len(legacy)} entry da {CACHE_PATH} a SQLite")
            _card_cache = legacy
        else:
            _card_cache = {row.card_name: json.loads(row.data) for row in rows}

        _loaded = True
    finally:
        await session.close()


def _load_legacy_json() -> dict:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


async def save_cache() -> None:
    """Scrive su SQLite solo le entry aggiunte/modificate o rimosse dall'ultimo
    salvataggio (UPSERT/DELETE mirati), non l'intera cache."""
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


def get_cached_card(card_name: str) -> Optional[dict]:
    return _card_cache.get(card_name.lower())


def set_cached_card(card_name: str, data: dict):
    key = card_name.lower()
    _card_cache[key] = data
    _dirty_upserts.add(key)
    _dirty_deletes.discard(key)


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
    key = card_name.lower()
    existed = key in _card_cache
    if existed:
        del _card_cache[key]
    _dirty_upserts.discard(key)
    _dirty_deletes.add(key)
    return existed


async def periodic_save_loop():
    while True:
        await asyncio.sleep(60)
        await save_cache()
