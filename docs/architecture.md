# System Architecture

## Overview

ClepshydraBot uses a **three-tier** architecture with a clean separation of responsibilities:

1. **Discord Layer (Cogs)** — user interface, slash commands, interactive components
2. **Service Layer** — business logic, algorithms, orchestration
3. **Repository Layer** — data access, CRUD, queries

On top of these sit the **Database Layer** (SQLAlchemy ORM) and the **Utilities Layer** (cross-cutting
functions).

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DISCORD API (Gateway + REST)                  │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
┌─────────────────────────────────┴───────────────────────────────────┐
│  COGS (Controller)                                                   │
│                                                                       │
│  ┌─────────────────────┐  ┌──────────────────────┐                   │
│  │  PresentationCog    │  │  TournamentSystemCog  │                   │
│  │  /presentati        │  │  18 slash commands    │                   │
│  │  on_member_join     │  │  modals, select menus │                   │
│  └────────┬────────────┘  └───────────┬──────────┘                   │
│           │                            │                              │
│  ┌────────┴────────────┐  ┌───────────┴──────────┐                   │
│  │  Tournament         │  │  Logger               │                   │
│  │  (deck_validation)  │  │  send_log()           │                   │
│  │  /artisan_check_deck│  ├──────────────────────┤                   │
│  └────────┬────────────┘  │  ErrorHandler         │                   │
│           │               │  tree.on_error        │                   │
│  ┌────────┴────────────┐  └──────────────────────┘                   │
│  │  Maintenance cogs   │                                             │
│  │  SPGOverrideUpdater │  /forced_rarity_refresh,                    │
│  │                     │  /invalidate_card_cache                     │
│  │  ArenaEventSchedule │  /forced_event_schedule_check               │
│  │  Updater            │                                             │
│  │  BanAnnouncement    │  /forced_ban_announcement_check             │
│  │  Updater            │                                             │
│  └─────────────────────┘                                             │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
┌─────────────────────────────────┴───────────────────────────────────┐
│  SERVICE LAYER (Business Logic)                                      │
│                                                                       │
│  ┌─────────────────────┐  ┌──────────────────────┐                   │
│  │  TournamentService  │  │  ArtisanService       │                   │
│  │  • create_tournament│  │  • validate_deck()    │                   │
│  │  • register_player  │  │  • _fetch_collection  │                   │
│  │  • submit_deck      │  │  • _is_arena_legal    │                   │
│  │  • start_tournament │  └──────────────────────┘                   │
│  │  • submit_result    │                                              │
│  │  • correct_result   │  ┌──────────────────────┐                   │
│  │  • generate_round   │  │  PresentationService  │                   │
│  │  • force_drop       │  │  • publish()          │                   │
│  │  • force_conclude   │  │  • _assign_*_role()   │                   │
│  │  • get_standings    │  └──────────────────────┘                   │
│  └────────┬────────────┘                                              │
│           │                                                           │
│  ┌────────┴────────────┐  ┌──────────────────────┐                   │
│  │  PairingEngine      │  │  StandingsCalculator  │                   │
│  │  • generate_round() │  │  • compute()          │                   │
│  │  • calculate_rounds │  └──────────────────────┘                   │
│  └─────────────────────┘                                              │
│                                                                       │
│  ┌─────────────────────┐                                              │
│  │  Rating (Glicko-2)  │                                              │
│  │  • rate_1vs1()      │                                              │
│  │  • rate_draw()      │                                              │
│  └─────────────────────┘                                              │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
┌─────────────────────────────────┴───────────────────────────────────┐
│  REPOSITORY LAYER (Data Access)                                      │
│                                                                       │
│  ┌─────────────────────┐  ┌──────────────────────┐                   │
│  │  BaseRepository[T]  │  │  UserRepository      │                   │
│  │  • get_by_id        │  │  • get_by_discord_id │                   │
│  │  • list_all         │  │  • get_or_create     │                   │
│  │  • add              │  │  • get_leaderboard   │                   │
│  │  • delete           │  └──────────────────────┘                   │
│  │  • count            │                                              │
│  └─────────────────────┘  ┌──────────────────────┐                   │
│                            │  TournamentRepository│                   │
│  ┌─────────────────────┐  │  • get_by_status     │                   │
│  │  MatchRepository    │  │  • get_with_players  │                   │
│  │  • get_by_tournament│  │  • find_by_name      │                   │
│  │  • get_by_tournament│  └──────────────────────┘                   │
│  │    _and_round       │                                              │
│  │  • get_current_round│  ┌──────────────────────┐                   │
│  │  • get_existing_    │  │  BanlistRepository   │                   │
│  │    pairings         │  │  • get_all_for_format│                   │
│  └─────────────────────┘  │  • add_card          │                   │
│                            │  • remove_card       │                   │
│  ┌─────────────────────┐  │  • import_from_file  │                   │
│  │  TournamentPlayer   │  └──────────────────────┘                   │
│  │  Repository         │                                              │
│  └─────────────────────┘                                              │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
┌─────────────────────────────────┴───────────────────────────────────┐
│  DATABASE / EXTERNAL APIs                                           │
│                                                                       │
│  ┌─────────────────────┐  ┌──────────────────────┐                   │
│  │  SQLite             │  │  Scryfall API         │                   │
│  │  tables:            │  │  • /cards/collection  │                   │
│  │  • users            │  │  • /cards/search      │                   │
│  │  • tournaments      │  └──────────────────────┘                   │
│  │  • tournament_players│                                            │
│  │  • matches          │  ┌──────────────────────┐                   │
│  │  • banned_cards     │  │  Discord API          │                   │
│  │  • cached_cards     │  │  • Gateway WebSocket  │                   │
│  └─────────────────────┘  │  • REST API           │                   │
│                            └──────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Patterns Used

| Pattern | Where | Description |
|---|---|---|
| **Repository** | `repositories/` | Hides data access behind dedicated interfaces |
| **Service Layer** | `services/` | Encapsulates business logic in service classes |
| **Strategy** | `PairingEngine`, `StandingsCalculator` | Interchangeable, stateless algorithms |
| **Observer** | Cogs' `on_member_join`, `on_message` | Listeners for Discord events |
| **Dependency Injection** | Service constructors | Bot and session passed in through the constructor |
| **Singleton** | `database/engine.py` | Global engine and session factory with lazy init |
| **Data Mapper** | `database/models.py` | SQLAlchemy ORM with explicit model classes |
| **MVP-like** | Cog = Controller, Service = Model, Embed = View | UI/logic separation |

---

## Main Flows

### User Presentation

```
User joins server
  → on_member_join() → 'Viandante' role + welcome message
  → /presentati
    → BasicPresentationModal (5 fields)
    → PreferencesView (4 select menus)
    → OptionalPresentationModal (4 optional fields)
    → PreviewView (confirm/cancel)
    → PresentationService.publish()
      → Field validation
      → Role change: Viandante → Planeswalker
      → Embed published to the presentation channel
      → Logger.send_log(INFO)
```

### Artisan Deck Validation

```
User → /artisan_check_deck → ArtisanDeckCheckModal
  → ArtisanService.validate_deck()
    1. _load_banlist() ← BanlistRepository (SQLite)
    2. check_banlist() → if banned → STOP
    3. _fetch_collection() → Scryfall API (or cache)
    4. _is_arena_artisan_legal() for each card
       → arena_overrides (SPG check)
       → prints_search_uri + game:arena
    5. Count: mainboard >= 60, sideboard <= 15
  → DeckValidationResult
  → DeckImageGenerator.create_deck_showcase() (if valid)
  → Embed + image → log and deck channels
```

### Tournament Lifecycle

```
Admin → /crea_torneo → TournamentService.create_tournament()
User  → /iscriviti → register_player() (no deck yet)
User  → /invia_deck → InviaDeckModal (deck validation) → submit_deck() (repeatable before the start)
Admin → /avvia_torneo → start_tournament() (refused while a player has no deck)
  → PairingEngine.generate_round(1) → random pairings
  → Embed published to the tournament channel
[Round played]
User  → /risultato → RisultatoView → submit_result()
Staff → /correggi_risultato → correct_result() (fixes a wrong or missing result)
Admin → /torneo_next_turn → generate_next_round()
  → If last round → concludes the tournament → _update_ratings() (Glicko-2)
  → Otherwise → PairingEngine.generate_round(N) → Swiss pairings
User  → /classifica → StandingsCalculator.compute() (3/1/0 + tiebreakers)
```

---

## Error Handling

- **Interaction catch-all** (since 3.5.6): an unhandled exception in a slash command, modal or view is caught
  by `utils/interaction_errors.py` — the user gets an ephemeral message ("unexpected error, staff has been
  notified", via `followup` if the interaction had already answered with a `defer()`), the log channel gets
  an `ERROR` `INTERACTION_ERROR` with source, exception and traceback tail, the console the full traceback.
  Three entry points, because discord.py routes errors differently: `cogs/error_handler.py` hooks
  `CommandTree.on_error` (slash commands; `CheckFailure`s such as those from `@is_admin()` are not logged,
  the check has already replied), and `ReportingModal`/`ReportingView` are the base class of every modal and
  view of the bot. Before 3.5.6 it didn't exist: an exception after a `defer()` left the user on
  "thinking..." and only reached the console
- **Retry**: Scryfall calls with exponential backoff (max 5 attempts)
- **Rate limiting**: asyncio semaphore to respect Scryfall limits
- **Scryfall outage ≠ illegal card**: `ScryfallUnavailable` leaves the deck unevaluated instead of marking
  cards illegal (see `docs/deck-validation.md`)
- **Atomic writes**: the monitors' state files and the SPG override JSON are written to `.tmp` then
  `os.replace()` (`save_json_state()` in `utils/sitemap_monitor.py`)
- **Async lock**: `asyncio.Lock()` around concurrent card cache saves
- **Bot startup**: `main.py` catches `discord.LoginFailure` (invalid/expired token) and any other startup
  exception, prints an explicit error to stderr and exits with a non-zero code, so a process supervisor
  (`pm2` in production, see `docs/infrastructure.md`) can detect the failure instead of a silent stop

---

## Testing

- `tests/tournament/`: the tournament service layer — `PairingEngine`, `Rating`, `StandingsCalculator`, embed
  builders, utilities, and `TournamentService` end to end (registration, deck submission, start, pairing,
  results and corrections, next round, forced drop, standings, rating).
- `tests/deck_validation/`: `ArtisanService.validate_deck()` (Scryfall mocked at the network edge), the
  SQLite card cache, SPG overrides.
- `tests/utils/`: the Wizards monitors, the shared sitemap logic, interaction error handling.
- Integration tests don't mock the DB: they run against a temporary SQLite per test (`tmp_path` + monkeypatch
  on `database.engine.DB_PATH`), wrapping the whole `init_db → logic → close_db` cycle in a single event loop
  (required by aiosqlite, which binds connections to the loop that created them).
- CI: `.github/workflows/ci.yml` runs `pytest` and `ruff check .` on every push/PR, both as blocking gates
  (lint since 1.7.1, once the pre-existing debt was cleared).
