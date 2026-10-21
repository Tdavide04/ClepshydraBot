import os

# features/tournaments/service.py and cog.py import database (-> database.engine
# -> config.config) at module top, so they need a populated config.config
# (GUILD_ID, channels, etc.). The purely algorithmic modules (pairing_engine,
# rating, standings) don't: until the 4.0.x restructure an eager
# services/__init__.py dragged the configuration into them too. pytest loads
# conftest.py before every test module in the folder, so these values are in
# os.environ before any application import can fail.
os.environ.setdefault("TEST_MODE", "True")
os.environ.setdefault("DISCORD_TOKEN_TEST", "test-token")
os.environ.setdefault("GUILD_ID_TEST", "111111111")
os.environ.setdefault("PRESENTATION_CHANNEL_ID_TEST", "1")
os.environ.setdefault("TOURNAMENT_CHANNEL_ID_TEST", "2")
os.environ.setdefault("PUBLIC_DECK_CHANNEL_ID_TEST", "3")
os.environ.setdefault("LOG_CHANNEL_ID", "4")
os.environ.setdefault("INITIAL_ROLE", "Viandante")
os.environ.setdefault("FINAL_ROLE", "Planeswalker")
