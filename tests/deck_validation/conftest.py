import os

# services/__init__.py eagerly imports TournamentService, which in turn needs
# a populated config.config (GUILD_ID, channels, etc.). features/deck_validation
# imports database (-> database.engine -> config.config) too, so any test in
# this folder drags in the same Discord configuration. pytest loads
# conftest.py before every test module in the folder, so these values are
# guaranteed to be in sys.environ before any `import features.deck_validation...`
# can fail. They must stay BEFORE every application import below
# (database.engine, features.deck_validation...), otherwise
# those imports fail themselves the moment this conftest.py is loaded.
# Same content as tests/tournament/conftest.py: duplicated on purpose so this
# folder stays runnable in isolation (`pytest tests/deck_validation -v`), not
# only as part of `pytest tests/`.
os.environ.setdefault("TEST_MODE", "True")
os.environ.setdefault("DISCORD_TOKEN_TEST", "test-token")
os.environ.setdefault("GUILD_ID_TEST", "111111111")
os.environ.setdefault("PRESENTATION_CHANNEL_ID_TEST", "1")
os.environ.setdefault("TOURNAMENT_CHANNEL_ID_TEST", "2")
os.environ.setdefault("PUBLIC_DECK_CHANNEL_ID_TEST", "3")
os.environ.setdefault("LOG_CHANNEL_ID", "4")
os.environ.setdefault("INITIAL_ROLE", "Viandante")
os.environ.setdefault("FINAL_ROLE", "Planeswalker")

import pytest  # noqa: E402

import database.engine as db_engine  # noqa: E402
import features.deck_validation.card_cache as card_cache  # noqa: E402
from features.deck_validation.service import invalidate_banlist_cache  # noqa: E402

# Fixtures shared by test_artisan_service.py and test_card_cache.py: they live
# here in conftest.py, not duplicated in each file, because pytest makes them
# available automatically to every module in this folder.


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Every test gets a temporary, isolated SQLite DB (same pattern as
    tests/tournament/test_tournament_service.py)."""
    monkeypatch.setattr(db_engine, "DB_PATH", str(tmp_path / "artisan_service_test.db"))
    db_engine._engine = None
    db_engine._async_session_maker = None
    yield


@pytest.fixture(autouse=True)
def isolated_card_cache(tmp_path, monkeypatch):
    """Resets features.deck_validation.card_cache's module state before every test.

    CACHE_PATH points to a nonexistent file so load_cache() (called by
    init_db() inside isolated_db/run_with_db) doesn't try to migrate the
    repository's real data/card_cache.json. _loaded=False forces load_cache()
    to start over from the test's temporary DB instead of skipping the load
    because an earlier test in the same pytest process already did it.
    """
    monkeypatch.setattr(card_cache, "CACHE_PATH", str(tmp_path / "card_cache_test.json"))
    monkeypatch.setattr(card_cache, "_card_cache", {})
    monkeypatch.setattr(card_cache, "_loaded", False)
    monkeypatch.setattr(card_cache, "_dirty_upserts", set())
    monkeypatch.setattr(card_cache, "_dirty_deletes", set())
    yield


@pytest.fixture(autouse=True)
def isolated_banlist_cache():
    """_banlist_cache is shared at module level (the 1.4.0 fix): without an
    explicit reset, the value loaded by one test would 'survive' into the
    next test's temporary DB."""
    invalidate_banlist_cache()
    yield
    invalidate_banlist_cache()
