import os

# services/__init__.py eagerly imports TournamentService, which in turn needs
# a populated config.config (GUILD_ID, channels, etc.). Any test in this
# folder that imports EVEN just services.pairing_engine or services.rating
# (purely algorithmic modules) therefore drags in the whole Discord
# configuration. pytest loads conftest.py before every test module in the
# folder, so these values are guaranteed to be in sys.environ before any
# `import services...` can fail.
os.environ.setdefault("TEST_MODE", "True")
os.environ.setdefault("DISCORD_TOKEN_TEST", "test-token")
os.environ.setdefault("GUILD_ID_TEST", "111111111")
os.environ.setdefault("PRESENTATION_CHANNEL_ID_TEST", "1")
os.environ.setdefault("TOURNAMENT_CHANNEL_ID_TEST", "2")
os.environ.setdefault("PUBLIC_DECK_CHANNEL_ID_TEST", "3")
os.environ.setdefault("LOG_CHANNEL_ID", "4")
os.environ.setdefault("INITIAL_ROLE", "Viandante")
os.environ.setdefault("FINAL_ROLE", "Planeswalker")
