# Database

## Overview

ClepshydraBot uses **SQLite** as its relational database, managed through **SQLAlchemy 2.0** with the async
driver **aiosqlite**. SQLite was chosen because of the hardware constraints (1 GB RAM, no separate process).

---

## Engine and Sessions (`database/engine.py`)

| Function | Description |
|---|---|
| `init_db()` | Creates the engine and tables, runs the migrations, imports the seed banlist, loads the card cache |
| `close_db()` | Disposes of the engine (called at shutdown) |
| `get_session()` | Returns an `AsyncSession` from the sessionmaker (`None` before `init_db()`) |

### Automatic Migrations

At startup, after `Base.metadata.create_all`, `init_db()` runs in order:

1. **`_migrate_banlist()`** — imports the banlist seed `seeds/banlist.txt` into `banned_cards` if the table is empty
2. **`_migrate_schema()`** — adds the missing columns listed in `_SCHEMA_MIGRATIONS` (table, column, DDL):
   - `tournament_players.deck_name`
   - `matches.p1_game_wins`, `matches.p2_game_wins`
   - `users.rating`, `users.rating_deviation`, `users.rating_volatility`, `users.rating_matches`,
     `users.last_rated_at`

   For each entry it explicitly checks whether the column already exists via `PRAGMA table_info(<table>)`
   before running the `ALTER TABLE` — it no longer relies on a generic `try/except Exception: pass`, which
   would also have hidden real errors (permissions, full disk, a column with an incompatible type). If the
   `ALTER TABLE` fails for any other reason, the error is printed to stdout with the `MIGRATION ERROR:`
   prefix instead of being silently ignored — bot startup still goes on, so a single unapplied column
   doesn't take down the whole service.

   To add a new migration, append a `(table, column, ddl)` tuple to `_SCHEMA_MIGRATIONS` in
   `database/engine.py` — `_migrate_schema()` needs no change.
3. **`load_cache()`** (`features/deck_validation/card_cache.py`) — loads the Scryfall card cache from the `cached_cards` table
   into memory; if the table is empty and `data/card_cache.json` still exists, migrates it once. See
   `docs/caching.md` for details.

---

## ORM Models (`database/models.py`)

### Table: `users`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | Internal ID |
| `discord_id` | Integer | UNIQUE, NOT NULL, INDEX | Discord ID |
| `nickname_arena` | String(100) | NULLABLE | MTGA nickname |
| `nome` | String(100) | NULLABLE | Display name (Italian column name, kept as is) |
| `created_at` | DateTime | DEFAULT now | Creation date |
| `rating` | Float | DEFAULT 1500.0 | Glicko-2 rating |
| `rating_deviation` | Float | DEFAULT 350.0 | Rating deviation |
| `rating_volatility` | Float | DEFAULT 0.06 | Glicko-2 volatility |
| `rating_matches` | Integer | DEFAULT 0 | Matches played |
| `last_rated_at` | DateTime | NULLABLE | Last update |

Relationships: `tournament_players` → TournamentPlayer

### Table: `tournaments`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | Tournament ID |
| `name` | String(200) | NOT NULL | Tournament name |
| `format` | String(50) | DEFAULT 'Artisan' | Format |
| `status` | Enum | DEFAULT 'registration' | registration/active/completed |
| `max_players` | Integer | NULLABLE | Player cap |
| `round_count` | Integer | NULLABLE | Total rounds |
| `created_at` | DateTime | DEFAULT now | |
| `started_at` | DateTime | NULLABLE | |
| `ended_at` | DateTime | NULLABLE | |

Relationships: `players` → TournamentPlayer, `matches` → Match

### Table: `tournament_players`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `tournament_id` | Integer | FK → tournaments.id | |
| `user_id` | Integer | FK → users.id | |
| `joined_at` | DateTime | DEFAULT now | |
| `dropped` | Boolean | DEFAULT False | Dropped |
| `seed` | Integer | NULLABLE | Pairing seed (tiebreaker in sorting); assigned as the tournament's highest seed + 1, dropped players included |
| `deck_name` | String(200) | NULLABLE | Deck name (migration) |

Relationships: `tournament` → Tournament, `user` → User, `matches_as_player1/2` → Match

### Table: `matches`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `tournament_id` | Integer | FK → tournaments.id | |
| `round_number` | Integer | NOT NULL | Round |
| `player1_id` | Integer | FK → tournament_players.id | |
| `player2_id` | Integer | FK → tournament_players.id, NULLABLE | NULL = bye |
| `winner_id` | Integer | FK → tournament_players.id, NULLABLE | |
| `result` | Enum | NULLABLE | win/loss/draw |
| `table_number` | Integer | NULLABLE | Table |
| `p1_game_wins` | Integer | NULLABLE | Games won by P1 (migration) |
| `p2_game_wins` | Integer | NULLABLE | Games won by P2 (migration) |

Relationships: `tournament` → Tournament, `player1/2` → TournamentPlayer

### Table: `banned_cards`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `card_name` | String(200) | UNIQUE, NOT NULL, INDEX | Card name |
| `format` | String(50) | DEFAULT 'Artisan' | Format |
| `created_at` | DateTime | DEFAULT now | |

### Table: `cached_cards`

Persistent cache of Scryfall cards (raw data + Artisan legality). Migrated from `data/card_cache.json` to
SQLite in September 2026 (1.6.0) — see `docs/caching.md` for how it works
(incremental load/save, TTL, legacy migration).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `card_name` | String(200) | PK | Card name, lowercase |
| `data` | Text | NOT NULL | Full Scryfall dict, serialized as JSON (base data + `artisan_legal` + `artisan_legal_checked_at`) |

No ORM relationship: managed directly by `features/deck_validation/card_cache.py`, not by a dedicated repository (the cache's
access pattern — an in-memory dict with dirty tracking — differs from the other CRUD-oriented repositories).

### Enums

```python
class TournamentStatus(enum.StrEnum):
    REGISTRATION = "registration"
    ACTIVE = "active"
    COMPLETED = "completed"

class MatchResult(enum.StrEnum):
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"
```

---

## Repository Pattern

### BaseRepository (`core/repository_base.py`)

Generic repository with basic CRUD:

| Method | Description |
|---|---|
| `get_by_id(id)` | Fetch by PK |
| `list_all()` | All records |
| `add(instance)` | Insert + commit + refresh |
| `delete(instance)` | Delete + commit |
| `count()` | Record count |

### UserRepository (`repositories/user_repository.py`)

| Method | Description |
|---|---|
| `get_by_discord_id(discord_id)` | Fetch by Discord ID |
| `get_or_create(discord_id)` | Find or create |
| `get_leaderboard(limit)` | Top N by rating, only users with at least one rated match |

### TournamentRepository (`repositories/tournament_repository.py`)

| Method | Description |
|---|---|
| `get_by_status(status)` | Tournaments filtered by status, newest first |
| `get_active()` / `get_open_for_registration()` | Shortcuts for `ACTIVE` / `REGISTRATION` |
| `find_by_name(name)` | Newest tournament whose name contains `name` (case-insensitive) |
| `get_with_players(id)` | Eager load with players |

### TournamentPlayerRepository

| Method | Description |
|---|---|
| `get_by_tournament(tournament_id, include_dropped=False)` | Active players by seed (eager load user); `include_dropped=True` also returns dropped ones, used by standings and rating |
| `get_by_tournament_and_user(tournament_id, user_id)` | One registration, dropped or not |
| `count_in_tournament(tournament_id)` | Count of active registrations |
| `max_seed(tournament_id)` | Highest seed ever assigned, dropped registrations included |

### MatchRepository

| Method | Description |
|---|---|
| `get_by_tournament(tournament_id)` | A tournament's matches (eager load players and users) |
| `get_by_tournament_and_round(tournament_id, round_number)` | Matches of one round |
| `get_existing_pairings(tournament_id)` | `(player1_id, player2_id)` pairs already played, byes excluded (anti-rematch) |
| `get_current_round(tournament_id)` | Highest round number, 0 if none |

### BanlistRepository (`features/deck_validation/banlist_repository.py`)

| Method | Description |
|---|---|
| `get_all_for_format(format)` | Set of banned cards (lowercase) |
| `add_card(card_name, format)` | Adds a card |
| `remove_card(card_name)` | Removes by exact name |
| `count()` | Banlist size |
| `import_from_file(path)` | Bulk import from txt (only if the table is empty) |

---

## Testing

`tests/tournament/test_tournament_service.py` exercises the whole DB stack (engine, sessions, repositories,
migrations) against a temporary SQLite file, isolated per test:

1. The `isolated_db` fixture (`tmp_path` + `monkeypatch`) points `database.engine.DB_PATH` to a temporary file
   and resets the `_engine`/`_async_session_maker` globals.
2. Each test runs `init_db()` → logic → `close_db()` in a **single** `asyncio.run()`: `aiosqlite` binds
   connections to the loop that created them, so setup/use/teardown can't be spread across separate event
   loops.
3. No mocks: SQLAlchemy queries really run against SQLite, `_migrate_schema()`'s `ALTER TABLE` migrations
   included.
