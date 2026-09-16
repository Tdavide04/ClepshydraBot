import os

# send_ban_announcement_log() (utils/ban_announcement.py) fa un import
# differito di COMUNICATION_CHANNEL_ID da config.config quando l'annuncio
# contiene modifiche reali - stesso motivo del deferred import in
# utils/permissions.py: eseguire questo test file da solo (senza passare
# prima da tests/tournament o tests/deck_validation, che popolano queste
# stesse variabili nei loro conftest.py) farebbe fallire config.config al
# primo accesso. Duplicato apposta invece che condiviso, come gli altri
# conftest.py di questo repo, cosi' tests/utils/ resta eseguibile in
# isolamento.
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
