from dotenv import load_dotenv
import os

load_dotenv()

TEST_MODE = os.getenv("TEST_MODE", "False").lower() == "true"

DISCORD_TOKEN = os.getenv(
    "DISCORD_TOKEN_TEST" if TEST_MODE else "DISCORD_TOKEN"
)

GUILD_ID = int(
    os.getenv(
        "GUILD_ID_TEST" if TEST_MODE else "GUILD_ID"
    )
)

PRESENTATION_CHANNEL_ID = int(
    os.getenv(
        "PRESENTATION_CHANNEL_ID_TEST" if TEST_MODE else "PRESENTATION_CHANNEL_ID"
        )
    )

TOURNAMENT_CHANNEL_ID = int(
    os.getenv(
        "TOURNAMENT_CHANNEL_ID_TEST" if TEST_MODE else "TOURNAMENT_CHANNEL_ID"
    ) or "0"
)

VERSION = os.getenv("VERSION")
if TEST_MODE: VERSION = VERSION + "-test"

PUBLIC_DECK_CHANNEL_ID = int(
    os.getenv(
        "PUBLIC_DECK_CHANNEL_ID_TEST" if TEST_MODE else "PUBLIC_DECK_CHANNEL_ID"
    )
)

LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

INITIAL_ROLE = os.getenv("INITIAL_ROLE")
FINAL_ROLE = os.getenv("FINAL_ROLE")

ADMIN_ROLE = os.getenv("ADMIN_ROLE", "Staff")

DB_PATH = os.getenv("DB_PATH", "data/clepshydra.db")
if TEST_MODE:
    DB_PATH = DB_PATH.replace(".db", "_test.db")