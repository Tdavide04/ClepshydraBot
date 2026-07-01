# ClepshydraBot

Discord bot for the **Clepshydra** Magic: The Gathering Arena community. Automates user verification, Artisan format deck validation, and Swiss tournament management.

## Features

- **Presentation System** — Multi-step modal wizard (`/presentati`) with role assignment
- **Artisan Deck Check** — Validate decks against banlist + Scryfall rarity check (`/artisan_check_deck`)
- **Swiss Tournaments** — Full tournament lifecycle: registration, pairing, results, standings
- **Deck Image Generator** — Dynamic PNG showcase with color-identity backgrounds
- **Rarity Override System** — Automatic SPG card rarity correction via Scryfall
- **Centralized Logging** — All events logged to a Discord channel with colored embeds

## Commands

| Command | Description | Access |
|---|---|---|
| `/presentati` | Open presentation wizard | All |
| `/artisan_check_deck` | Validate Artisan deck | All |
| `/torneo crea` | Create tournament | Admin |
| `/torneo avvia` | Start tournament | Admin |
| `/torneo prossimo_turno` | Generate next round | Admin |
| `/iscriviti` | Register for tournament | All |
| `/risultato` | Submit match result | All |
| `/classifica` | View standings | All |
| `/turni` | View current pairings | All |
| `/update_spg_overrides` | Update rarity overrides | Admin |

## Tech Stack

- **Python 3.12+** — Core language
- **discord.py** — Discord API (slash commands, modals, views)
- **SQLAlchemy 2.0 + aiosqlite** — Async ORM + SQLite
- **aiohttp** — Async HTTP client for Scryfall API
- **Pillow** — Deck image generation

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Discord Gateway                       │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────┴───────────────────────────────────┐
│                     Cogs (Discord layer)                 │
│  presentation/    tournament/    tournament_system/      │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────┴───────────────────────────────────┐
│                   Service Layer                          │
│  PresentationService    TournamentService                │
│  PairingEngine          StandingsCalculator              │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────┴───────────────────────────────────┐
│                  Repository Layer                        │
│  UserRepository    TournamentRepository    MatchRepository│
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────┴───────────────────────────────────┐
│  SQLite              │         Scryfall API              │
│  (data/clepsydra.db) │         (card data)               │
└──────────────────────┘                                   │
```

## Project Structure

```
ClepsydraBot/
├── cogs/
│   ├── presentation/        # User presentation wizard
│   ├── tournament/          # Artisan deck validation
│   ├── tournament_system/   # Swiss tournament management
│   ├── logger.py            # Centralized logging
│   └── spg_override_updater.py
├── services/                # Business logic
│   ├── tournament_service.py
│   ├── pairing_engine.py
│   └── standings.py
├── repositories/            # Data access layer
│   ├── base.py
│   ├── user_repository.py
│   └── tournament_repository.py
├── database/                # SQLAlchemy ORM
│   ├── engine.py
│   └── models.py
├── utils/                   # Utilities
│   ├── card_cache.py
│   ├── arena_overrides.py
│   └── deck_image_generator.py
├── config/
│   └── config.py
├── assets/backgrounds/      # MTG color-themed backgrounds
├── data/                    # Runtime data (cache, db)
├── main.py
└── requirements.txt
```

## Quick Start

```bash
git clone https://github.com/Tdavide04/ClepshydraBot.git
cd ClepshydraBot
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Discord token and channel IDs
python main.py
```

### Prerequisites

- Python 3.12+
- Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))
- Discord server with appropriate intents enabled (Member, Message Content)

## Development

```bash
# Test mode (uses separate channels and test database)
TEST_MODE=True python main.py
```

The bot auto-creates `data/clepsydra.db` on first run. View it with:

```bash
pip install sqlitebrowser
sqlitebrowser data/clepsydra.db
```

## License

MIT License — see [LICENSE](LICENSE).

## Author

**Davide Trischitta** — [Tdavide04](https://github.com/Tdavide04)
