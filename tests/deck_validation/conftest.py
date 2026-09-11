import os

# services/__init__.py importa eagerly TournamentService, che a sua volta
# richiede config.config popolato (GUILD_ID, canali, ecc.). cogs/deck_validation
# importa a sua volta database (-> database.engine -> config.config), quindi
# qualunque test in questa cartella trascina la stessa configurazione Discord.
# conftest.py viene caricato da pytest prima di ogni modulo di test nella
# cartella, quindi questi valori sono garantiti in sys.environ prima che
# qualunque `import cogs.deck_validation...` possa fallire.
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
