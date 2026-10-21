import os

# These tests import every application module, main.py included, and most of
# them load config.config at import time. Duplicated on purpose, like the
# other conftest.py files in this repo, so tests/core/ stays runnable in
# isolation. Must stay before any application import.
os.environ.setdefault("TEST_MODE", "True")
os.environ.setdefault("DISCORD_TOKEN_TEST", "test-token")
os.environ.setdefault("GUILD_ID_TEST", "111111111")
os.environ.setdefault("PRESENTATION_CHANNEL_ID_TEST", "1")
os.environ.setdefault("TOURNAMENT_CHANNEL_ID_TEST", "2")
os.environ.setdefault("PUBLIC_DECK_CHANNEL_ID_TEST", "3")
os.environ.setdefault("COMUNICATION_CHANNEL_ID_TEST", "5")
os.environ.setdefault("LOG_CHANNEL_ID", "4")
os.environ.setdefault("INITIAL_ROLE", "Viandante")
os.environ.setdefault("FINAL_ROLE", "Planeswalker")
