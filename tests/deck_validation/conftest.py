import os

# services/__init__.py importa eagerly TournamentService, che a sua volta
# richiede config.config popolato (GUILD_ID, canali, ecc.). cogs/deck_validation
# importa a sua volta database (-> database.engine -> config.config), quindi
# qualunque test in questa cartella trascina la stessa configurazione Discord.
# conftest.py viene caricato da pytest prima di ogni modulo di test nella
# cartella, quindi questi valori sono garantiti in sys.environ prima che
# qualunque `import cogs.deck_validation...` possa fallire. Devono restare
# PRIMA di ogni import applicativo qui sotto (database.engine, utils.card_cache,
# cogs.deck_validation...), altrimenti quegli import falliscono loro stessi
# nel momento in cui questo conftest.py viene caricato.
# Stesso identico contenuto di tests/tournament/conftest.py: duplicato
# deliberatamente cosi' questa cartella resta eseguibile in isolamento
# (`pytest tests/deck_validation -v`), non solo come parte di `pytest tests/`.
os.environ.setdefault("TEST_MODE", "True")
os.environ.setdefault("DISCORD_TOKEN_TEST", "test-token")
os.environ.setdefault("GUILD_ID_TEST", "111111111")
os.environ.setdefault("PRESENTATION_CHANNEL_ID_TEST", "1")
os.environ.setdefault("TOURNAMENT_CHANNEL_ID_TEST", "2")
os.environ.setdefault("PUBLIC_DECK_CHANNEL_ID_TEST", "3")
os.environ.setdefault("LOG_CHANNEL_ID", "4")
os.environ.setdefault("INITIAL_ROLE", "Viandante")
os.environ.setdefault("FINAL_ROLE", "Planeswalker")
os.environ.setdefault("VERSION", "test")

import pytest  # noqa: E402

import database.engine as db_engine  # noqa: E402
import utils.card_cache as card_cache  # noqa: E402
from cogs.deck_validation.service import invalidate_banlist_cache  # noqa: E402


# Fixture condivise tra test_artisan_service.py e test_card_cache.py: qui in
# conftest.py, non duplicate nei singoli file, perche' pytest le rende
# disponibili automaticamente a ogni modulo di questa cartella.

@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Ogni test riceve un DB SQLite temporaneo e isolato (stesso pattern di
    tests/tournament/test_tournament_service.py)."""
    monkeypatch.setattr(db_engine, "DB_PATH", str(tmp_path / "artisan_service_test.db"))
    db_engine._engine = None
    db_engine._async_session_maker = None
    yield


@pytest.fixture(autouse=True)
def isolated_card_cache(tmp_path, monkeypatch):
    """Resetta lo stato di modulo di utils.card_cache prima di ogni test.

    CACHE_PATH punta a un file inesistente cosi' load_cache() (chiamata da
    init_db() dentro isolated_db/run_with_db) non tenta di migrare il vero
    data/card_cache.json del repository. _loaded=False forza load_cache() a
    ripartire dal DB temporaneo del test invece di saltare il caricamento
    perche' gia' fatto da un test precedente nello stesso processo pytest.
    """
    monkeypatch.setattr(card_cache, "CACHE_PATH", str(tmp_path / "card_cache_test.json"))
    monkeypatch.setattr(card_cache, "_card_cache", {})
    monkeypatch.setattr(card_cache, "_loaded", False)
    monkeypatch.setattr(card_cache, "_dirty_upserts", set())
    monkeypatch.setattr(card_cache, "_dirty_deletes", set())
    yield


@pytest.fixture(autouse=True)
def isolated_banlist_cache():
    """_banlist_cache e' condivisa a livello di modulo (fix dello Step 1): senza
    reset esplicito, il valore caricato da un test 'sopravviverebbe' al DB
    temporaneo del test successivo."""
    invalidate_banlist_cache()
    yield
    invalidate_banlist_cache()
