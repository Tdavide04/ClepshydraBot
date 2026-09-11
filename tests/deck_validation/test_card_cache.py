import asyncio
import json

import utils.card_cache as card_cache
from database import init_db, close_db, get_session
from database.models import CachedCard


def run_with_db(scenario):
    """Stesso pattern di test_artisan_service.py / test_tournament_service.py:
    init_db + logica + close_db in un unico event loop."""
    async def _wrapper():
        await init_db()
        try:
            return await scenario()
        finally:
            await close_db()
    return asyncio.run(_wrapper())


async def _raw_rows() -> dict:
    """Legge direttamente la tabella cached_cards, bypassando _card_cache, per
    verificare cosa e' stato davvero scritto su SQLite."""
    session = get_session()
    try:
        from sqlalchemy import select
        result = await session.execute(select(CachedCard))
        return {row.card_name: json.loads(row.data) for row in result.scalars()}
    finally:
        await session.close()


class TestLoadCache:

    def test_load_cache_starts_empty_with_no_legacy_file(self, isolated_db):
        async def scenario():
            return dict(card_cache._card_cache)

        assert run_with_db(scenario) == {}

    def test_load_cache_migrates_legacy_json_once(self, isolated_db, tmp_path, monkeypatch):
        legacy_path = tmp_path / "legacy_card_cache.json"
        legacy_path.write_text(
            json.dumps({"lightning bolt": {"name": "Lightning Bolt", "artisan_legal": True}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(card_cache, "CACHE_PATH", str(legacy_path))

        async def scenario():
            in_memory = dict(card_cache._card_cache)
            on_disk = await _raw_rows()
            return in_memory, on_disk

        in_memory, on_disk = run_with_db(scenario)
        assert in_memory == {"lightning bolt": {"name": "Lightning Bolt", "artisan_legal": True}}
        assert on_disk == in_memory, "la migrazione deve scrivere subito su SQLite, non solo in RAM"


class TestSaveCache:

    def test_save_cache_persists_only_dirty_entries(self, isolated_db):
        async def scenario():
            card_cache.set_cached_card("Card A", {"name": "Card A"})
            card_cache.set_cached_card("Card B", {"name": "Card B"})
            await card_cache.save_cache()
            return await _raw_rows()

        rows = run_with_db(scenario)
        assert rows == {"card a": {"name": "Card A"}, "card b": {"name": "Card B"}}
        assert card_cache._dirty_upserts == set(), "save_cache deve svuotare i dirty dopo il commit"

    def test_save_cache_is_noop_without_dirty_entries(self, isolated_db):
        async def scenario():
            await card_cache.save_cache()  # nessuna modifica pendente
            return await _raw_rows()

        assert run_with_db(scenario) == {}

    def test_save_cache_updates_existing_row(self, isolated_db):
        async def scenario():
            card_cache.set_cached_card("Card A", {"name": "Card A", "cmc": 1})
            await card_cache.save_cache()

            card_cache.set_cached_card("Card A", {"name": "Card A", "cmc": 2})
            await card_cache.save_cache()

            return await _raw_rows()

        rows = run_with_db(scenario)
        assert rows == {"card a": {"name": "Card A", "cmc": 2}}

    def test_invalidate_card_deletes_on_next_save(self, isolated_db):
        async def scenario():
            card_cache.set_cached_card("Card A", {"name": "Card A"})
            await card_cache.save_cache()

            removed = card_cache.invalidate_card("card a")
            await card_cache.save_cache()

            return removed, await _raw_rows()

        removed, rows = run_with_db(scenario)
        assert removed is True
        assert rows == {}

    def test_invalidate_card_never_persisted_is_noop(self, isolated_db):
        """Invalida una carta aggiunta e mai salvata: non deve generare una
        DELETE per una riga mai esistita ne' un errore."""
        async def scenario():
            card_cache.set_cached_card("Card A", {"name": "Card A"})
            removed = card_cache.invalidate_card("card a")
            await card_cache.save_cache()
            return removed, await _raw_rows()

        removed, rows = run_with_db(scenario)
        assert removed is True
        assert rows == {}

    def test_reload_after_restart_reads_persisted_data(self, isolated_db):
        """Simula un riavvio del bot: dopo save_cache(), azzerare lo stato in
        memoria e richiamare load_cache() deve ripristinare gli stessi dati."""
        async def scenario():
            card_cache.set_cached_card("Card A", {"name": "Card A"})
            await card_cache.save_cache()

            card_cache._card_cache.clear()
            card_cache._loaded = False
            await card_cache.load_cache()

            return dict(card_cache._card_cache)

        assert run_with_db(scenario) == {"card a": {"name": "Card A"}}
