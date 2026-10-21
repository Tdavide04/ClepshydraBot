# ClepshydraBot

Discord helper bot for the **Clepshydra** Magic: The Gathering Arena community: member onboarding, Artisan
format deck validation and the banlist, and monitors for Wizards' Arena Event Schedule and Banned and Restricted
pages. The Swiss tournament system is disabled since 4.0.0 (tournaments are hosted elsewhere): its code stays in
the repo but isn't loaded (`docs/adr/0004-helper-only-tournaments-disabled.md`).

The bot talks to its users in Italian (command names, replies, community announcements); code, logs and
documentation are in English (see `docs/adr/0003-project-language.md`).

## Features

- **Presentation System** — Multi-step modal wizard (`/presentati`) with role assignment
- **Artisan Deck Check** — Validate decks against banlist + Scryfall rarity check (`/artisan_check_deck`)
- **Deck Image Generator** — Dynamic PNG showcase with color-identity backgrounds
- **Rarity Override System** — Automatic SPG card rarity correction via Scryfall
- **Arena Event Schedule Monitor** — Detects when the current MTG Arena "Event Schedule" page (Quick Draft rotation, Arena Direct, etc.) is new or updated and posts a monthly calendar image to Discord (one row per category, color-coded by family: Draft, Flashback, Sealed & Cube, Metagame, Community), to both the staff log channel and a public community channel
- **Ban Announcement Monitor** — Detects new official "Banned and Restricted Announcement" posts and notifies both the staff log channel and a public community channel with per-format changes (notification only — the bot's own Artisan banlist stays manually curated)
- **Centralized Logging** — All events logged to a Discord channel with colored embeds

## Commands

| Command | Description | Access |
|---|---|---|
| `/presentati` | Open presentation wizard | All |
| `/artisan_check_deck` | Validate Artisan deck | All |
| `/banlist` | View the Artisan banlist | All |
| `/banlist_aggiungi` / `/banlist_rimuovi` | Add/remove a card from the Artisan banlist | Admin |
| `/invalidate_card_cache` | Force a full Scryfall re-check of one card | Admin |
| `/forced_rarity_refresh` | Force an immediate rarity override check (also runs automatically every week) | Admin |
| `/forced_event_schedule_check` | Force an immediate re-check of the latest Arena "Event Schedule" page (also runs automatically every 2 hours) | Admin |
| `/forced_ban_announcement_check` | Force an immediate re-check of the latest Banned and Restricted Announcement (also runs automatically every 2 hours) | Admin |

Full details (parameters, behaviour, source location) in `docs/commands.md`.

## Tech Stack

- **Python 3.12+** — Core language
- **discord.py** — Discord API (slash commands, modals, views)
- **SQLAlchemy 2.0 + aiosqlite** — Async ORM + SQLite
- **aiohttp** — Async HTTP client for Scryfall API
- **Pillow** — Deck image generation, Arena Event Schedule calendar image generation

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Discord Gateway                       │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────┴───────────────────────────────────┐
│                     Cogs (Discord layer)                 │
│  features/: onboarding, deck_validation, monitors        │
│  features/tournaments (disabled)                         │
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
│  UserRepository  TournamentRepository  BanlistRepository │
│  TournamentPlayerRepository            MatchRepository   │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────┴───────────────────────────────────┐
│  SQLite              │         Scryfall API              │
│ (data/clepshydra.db) │         (card data)               │
└──────────────────────┘                                   │
```

## Project Structure

```
ClepshydraBot/
├── core/                    # Cross-cutting, used by every feature
│   ├── logger.py            # Log channel (extension)
│   ├── error_handler.py     # Global slash command error handler (extension)
│   ├── interaction_errors.py  # ReportingModal / ReportingView
│   ├── results.py           # ServiceResult (structured service outcome)
│   ├── repository_base.py   # BaseRepository
│   ├── json_state.py        # Atomic JSON state files
│   ├── console.py           # Timestamped console log()
│   └── permissions.py       # @is_admin() check
├── features/
│   ├── onboarding/          # /presentati wizard, welcome and presentation channel rules
│   ├── deck_validation/     # Artisan deck validation, banlist, Scryfall cache, SPG overrides
│   │   ├── cog.py           # /artisan_check_deck + banlist commands
│   │   ├── spg_cog.py       # /forced_rarity_refresh, /invalidate_card_cache
│   │   ├── service.py       # ArtisanService
│   │   ├── validators.py, models.py, embeds.py
│   │   ├── banlist_service.py, banlist_repository.py
│   │   ├── card_cache.py
│   │   ├── arena_overrides.py
│   │   └── image.py         # Deck showcase image
│   ├── monitors/            # Wizards monitors: Event Schedule, Banned and Restricted
│   │   ├── sitemap.py       # Shared sitemap fetch and newest-page selection
│   │   ├── event_schedule.py
│   │   ├── calendar_image.py  # Monthly event calendar images
│   │   ├── ban_announcement.py
│   │   ├── event_schedule_cog.py
│   │   └── ban_announcement_cog.py
│   └── tournaments/         # Swiss tournaments, Glicko-2 (disabled, not loaded)
│       ├── cog.py, service.py
│       ├── pairing_engine.py, standings.py, rating.py
│       ├── repository.py, user_repository.py
│       └── embeds.py, logic.py
├── database/                # SQLAlchemy ORM
│   ├── engine.py
│   └── models.py
├── config/
│   └── config.py
├── assets/backgrounds/      # MTG color-themed backgrounds
├── data/                    # Runtime data (db, monitor state, SPG overrides), not in git
├── seeds/                   # Tracked starting data: banlist.txt, arena_rarity.json
├── main.py
├── pyproject.toml           # Tool config: ruff, pytest
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
pip install -r requirements-dev.txt   # adds pytest, ruff and pre-commit
pre-commit install --hook-type pre-commit --hook-type commit-msg   # once per clone

# Test mode (uses separate channels and test database)
TEST_MODE=True python main.py

# Tests, lint and formatting (all blocking gates in CI)
python -m pytest
python -m ruff check .
python -m ruff format --check .   # `python -m ruff format .` to fix
```

The working standard (test-first, Conventional Commits, docs kept truthful) is described in `CLAUDE.md`.

The bot auto-creates `data/clepshydra.db` on first run (`data/clepshydra_test.db` in test mode). View it
with [DB Browser for SQLite](https://sqlitebrowser.org) — a desktop app, not a pip package (e.g.
`sudo apt install sqlitebrowser` on Debian/Ubuntu):

```bash
sqlitebrowser data/clepshydra.db
```

## Documentation

| Topic | Document |
|---|---|
| Architecture | `docs/architecture.md` |
| Commands | `docs/commands.md` |
| Tournaments (disabled) | `docs/tournaments.md` |
| Deck validation and banlist | `docs/deck-validation.md`, `docs/banlist-system.md` |
| Caching, Scryfall, Wizards monitors | `docs/caching.md` |
| Onboarding | `docs/onboarding.md` |
| Database | `docs/database.md` |
| Infrastructure and deployment | `docs/infrastructure.md`, `docs/technical-report.md` |
| Roadmap and decisions | `docs/roadmap.md`, `docs/adr/` |

## License

MIT License — see [LICENSE](LICENSE).

## Author

**Davide Trischitta** — [Tdavide04](https://github.com/Tdavide04)
