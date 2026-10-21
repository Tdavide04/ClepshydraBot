import os

# send_ban_announcement_log() (utils/ban_announcement.py) lazily imports
# COMUNICATION_CHANNEL_ID from config.config when the announcement has real
# changes - same reason as the lazy import in utils/permissions.py: running
# this test file alone (without going through tests/tournament or
# tests/deck_validation first, whose conftest.py files populate these same
# variables) would make config.config fail on first access. Duplicated on
# purpose rather than shared, like the other conftest.py files in this repo,
# so tests/utils/ stays runnable in isolation.
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
