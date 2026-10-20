import asyncio
import json

import utils.card_cache as card_cache
from database import init_db, close_db, get_session
from database.models import CachedCard


def run_with_db(scenario):
    """Same pattern as test_artisan_service.py / test_tournament_service.py:
    init_db + logic + close_db in a single event loop."""
    async def _wrapper():
        await init_db()
        try:
            return await scenario()
        finally:
            await close_db()
    return asyncio.run(_wrapper())


async def _raw_rows() -> dict:
    """Reads the cached_cards table directly, bypassing _card_cache, to check
    what was actually written to SQLite."""
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
        assert on_disk == in_memory, "the migration must write to SQLite right away, not only to RAM"


class TestSaveCache:

    def test_save_cache_persists_only_dirty_entries(self, isolated_db):
        async def scenario():
            card_cache.set_cached_card("Card A", {"name": "Card A"})
            card_cache.set_cached_card("Card B", {"name": "Card B"})
            await card_cache.save_cache()
            return await _raw_rows()

        rows = run_with_db(scenario)
        assert rows == {"card a": {"name": "Card A"}, "card b": {"name": "Card B"}}
        assert card_cache._dirty_upserts == set(), "save_cache must clear the dirty sets after the commit"

    def test_save_cache_is_noop_without_dirty_entries(self, isolated_db):
        async def scenario():
            await card_cache.save_cache()  # no pending change
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
        """Invalidates a card added and never saved: it must produce neither a
        DELETE for a row that never existed nor an error."""
        async def scenario():
            card_cache.set_cached_card("Card A", {"name": "Card A"})
            removed = card_cache.invalidate_card("card a")
            await card_cache.save_cache()
            return removed, await _raw_rows()

        removed, rows = run_with_db(scenario)
        assert removed is True
        assert rows == {}

    def test_reload_after_restart_reads_persisted_data(self, isolated_db):
        """Simulates a bot restart: after save_cache(), clearing the in-memory
        state and calling load_cache() again must restore the same data."""
        async def scenario():
            card_cache.set_cached_card("Card A", {"name": "Card A"})
            await card_cache.save_cache()

            card_cache._card_cache.clear()
            card_cache._loaded = False
            await card_cache.load_cache()

            return dict(card_cache._card_cache)

        assert run_with_db(scenario) == {"card a": {"name": "Card A"}}


class TestPeriodicSaveLoop:

    def test_a_failed_save_does_not_stop_the_loop(self, monkeypatch, capsys):
        """Regression: the loop didn't handle exceptions - a single
        save_cache() error (e.g. a locked DB) silently killed the task, and the
        cache was no longer saved until restart."""
        calls = []

        async def flaky_save():
            calls.append(len(calls))
            if len(calls) == 1:
                raise RuntimeError("database is locked")
            if len(calls) == 3:
                # Exit from the infinite loop: this is how the task really
                # gets stopped (cancellation), and it must not be swallowed.
                raise asyncio.CancelledError

        monkeypatch.setattr(card_cache, "save_cache", flaky_save)

        try:
            asyncio.run(card_cache.periodic_save_loop(interval_seconds=0))
        except asyncio.CancelledError:
            pass

        assert len(calls) == 3, "after the error the loop must keep saving"
        assert "[CARD CACHE] save failed" in capsys.readouterr().out

    def test_dirty_entries_survive_a_failed_save(self, isolated_db, monkeypatch):
        """Retrying only makes sense if the changes stay pending: save_cache()
        clears _dirty_upserts only after a successful commit."""
        async def scenario():
            card_cache.set_cached_card("Lightning Bolt", {"name": "Lightning Bolt"})

            class BrokenSession:
                async def get(self, *args):
                    raise RuntimeError("database is locked")

                async def close(self):
                    pass

            import database
            real_get_session = database.get_session
            monkeypatch.setattr(database, "get_session", lambda: BrokenSession())
            try:
                await card_cache.save_cache()
            except RuntimeError:
                pass
            monkeypatch.setattr(database, "get_session", real_get_session)

            assert "lightning bolt" in card_cache._dirty_upserts
            await card_cache.save_cache()
            return await _raw_rows()

        rows = run_with_db(scenario)
        assert "lightning bolt" in rows
