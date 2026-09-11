# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ClepshydraBot — a Discord bot (discord.py) for the "Clepshydra" MTG Arena community. It handles member
onboarding/presentation, Artisan-format deck validation against Scryfall, and Swiss-style tournaments
with Glicko-2 rating. Slash commands and UI are in Italian; code identifiers are in English.

Work happens on `feature/v2`; `main` only receives merges via PR from `feature/v2` — do not commit
directly to `main`.

## Commands

```bash
# Install deps (production)
pip install -r requirements.txt

# Install deps (development: adds pytest, ruff)
pip install -r requirements-dev.txt

# Run the bot (requires .env, see .env.example)
python main.py

# Run in test mode (separate token/guild/channels/db, see config/config.py)
TEST_MODE=True python main.py

# Run tests (same invocation as CI: .github/workflows/ci.yml)
pytest tests/ -v
python -m pytest                          # equivalent; python -m adds cwd to sys.path itself
pytest tests/tournament/test_pairing_engine.py
pytest tests/tournament/test_pairing_engine.py::TestCalculateRounds::test_otto_giocatori -v

# Lint (blocking gate in CI — legacy/ is excluded, see ruff.toml)
ruff check .

# Inspect the SQLite DB
sqlitebrowser data/clepshydra.db
```

`pytest.ini` sets `pythonpath = .` — required for the bare `pytest tests/` invocation (used by CI) to
find top-level modules (`services`, `database`, `utils`); without it, only `python -m pytest` would work,
since that form adds the cwd to `sys.path` itself. Both `tests/tournament/conftest.py` and
`tests/deck_validation/conftest.py` seed the same env vars (duplicated on purpose, not shared, so each
directory stays runnable in isolation) that `services/__init__.py` needs at import time (it eagerly
imports `TournamentService`, which requires `config.config` to be populated) — any test importing even a
pure-logic module like `services.pairing_engine` transitively needs these, and so does anything importing
`cogs.deck_validation.service` (it imports `database`, which imports `database.engine` → `config.config`).
Note the env var seeding in a conftest.py must run **before** any application import in that same file —
`database.engine`/`utils.card_cache`/`cogs.deck_validation.service` all transitively import
`config.config` at module load time. Within `tests/deck_validation/`, `isolated_db` / `isolated_card_cache`
/ `isolated_banlist_cache` fixtures live in `conftest.py` (shared across `test_artisan_service.py` and
`test_card_cache.py`, unlike the env vars) and reset `utils.card_cache`'s module globals
(`_card_cache`, `_loaded`, `_dirty_upserts`, `_dirty_deletes`) each test — required since Step 4 made
`_loaded` persist across `load_cache()` calls within a process, which would otherwise skip reloading from
a fresh per-test temp DB.

Suite: 112 tests total, no `pytest-asyncio` — async integration tests
(`tests/tournament/test_tournament_service.py`, `tests/deck_validation/test_artisan_service.py`,
`tests/deck_validation/test_card_cache.py`, `tests/deck_validation/test_arena_overrides.py`) instead
wrap each scenario in a single `asyncio.run()` call,
since aiosqlite connections are bound to the event loop that created them. `ArtisanService` tests mock
`_post_with_retry`/`_get_with_retry` (swap them for plain async functions on the instance) instead of
touching `aiohttp.ClientSession` — no real network calls, and it doubles as a regression test for the
module-level banlist cache (Step 1) and the `artisan_legal` TTL (Step 3).

## Architecture

Three-tier layering, consistently applied: **Cogs → Services → Repositories → Database**, plus a
cross-cutting `utils/` layer. Read `docs/architettura.md` for the full diagram; it's accurate and worth
opening before large changes. Other useful docs: `docs/deck-validation.md`, `docs/banlist-system.md`,
`docs/caching.md`, `docs/tornei.md`, `docs/comandi.md`, `docs/database.md`,
`docs/roadmap-miglioramenti.md` (tracked technical debt and in-progress improvement steps).

- **`cogs/`** — Discord-facing layer (slash commands, modals, views, embeds). Three feature cogs:
  `presentation/` (onboarding wizard), `deck_validation/` (Artisan deck legality checks, formerly named
  `tournament/` — see below), `tournament_system/` (Swiss tournaments, one large `cog.py` with ~14
  slash commands). `logger.py` is a Logger cog other cogs fetch via `bot.get_cog('Logger')` and call
  `send_log(level, event, info)` on, to post colored embeds to a central log channel.
- **`services/`** — Business logic, stateless where possible. `tournament_service.py` orchestrates the
  tournament lifecycle; `pairing_engine.py` generates Swiss pairings (bye handling, anti-rematch);
  `standings.py` computes standings (3/1/0 scoring + tiebreakers); `rating.py` implements Glicko-2.
- **`repositories/`** — Data access only, no business logic. `base.py` defines a generic
  `BaseRepository[T]` (get_by_id/list_all/add/delete/count); feature repositories extend it
  (`UserRepository`, `TournamentRepository`, `BanlistRepository`, plus a `TournamentPlayerRepository`).
- **`database/`** — SQLAlchemy 2.0 async ORM. `models.py` defines `User`, `Tournament`,
  `TournamentPlayer`, `Match`, `BannedCard` (see file for full schema). `engine.py` holds a lazily
  initialized global async engine/session-maker (singleton pattern) and runs ad-hoc `ALTER TABLE ...`
  migrations by hand inside `_migrate_schema()` at startup (no Alembic) — when adding a column to an
  existing table, append a `(table, column, ddl)` tuple to `_SCHEMA_MIGRATIONS` there; the loop checks
  `PRAGMA table_info(<table>)` before running each `ALTER TABLE` and only logs-and-continues
  (`ERRORE migrazione: ...`) on an unexpected failure, instead of swallowing every exception including
  real ones. `init_db()` also imports `cards.txt` into `banned_cards` on first run via
  `_migrate_banlist()`, but only if the table is empty.
- **`utils/`** — Cross-cutting helpers: `card_cache.py` (Scryfall response cache), `arena_overrides.py`
  (SPG rarity overrides), `deck_image_generator.py` (Pillow-based deck showcase PNGs), `permissions.py`
  (`@is_admin()` app-command check based on a configured Discord role name), `tournament_embeds.py`,
  `tournament_logic.py`.

### Config and environment

`config/config.py` loads `.env` via `python-dotenv` and reads all settings as module-level constants
(no pydantic/settings class). `TEST_MODE` selects `_TEST`-suffixed env vars (token, guild, channels, db
path) at import time — there is no runtime toggle. `main.py` constructs the bot, calls `init_db()`,
dynamically loads every module/package under `cogs/`, starts two background tasks —
`periodic_save_loop()` (card cache autosave, every 60s) and `periodic_spg_refresh_loop()` (SPG rarity
override auto-refresh, every 7 days — see below) — and syncs the slash command tree to a single guild
(`GUILD_ID`) rather than globally. Startup
failures (`discord.LoginFailure` and other exceptions in `setup_hook`/`bot.run`) are caught, logged to
stderr with a `FATAL:` prefix, and exit non-zero instead of failing silently.

### Deployment

Production runs on an Oracle Cloud VM (1 OCPU / 1 GB RAM — see `docs/ClepshydraBot_Resoconto_Tecnico.md`
and `docs/infrastruttura.md`) under `pm2`, which restarts the process on crash. `deploy/clepshydrabot.service`
(systemd) exists in the repo as an alternative but is **not** what's installed in production — don't
assume systemd when writing deployment-related docs or scripts.

### Deck validation pipeline (Artisan format)

`ArtisanService.validate_deck()` (`cogs/deck_validation/service.py`) runs, in order:
1. Parse the pasted decklist (`validators.parse_decklist`) into mainboard/sideboard `DeckEntry` lists.
2. Check names against a module-level banlist cache (`_banlist_cache` in
   `cogs/deck_validation/service.py`, shared by every `ArtisanService` instance — the bot creates two,
   one in `cogs/tournament_system/cog.py` and one in `cogs/deck_validation/__init__.py`). Admin
   `/banlist_aggiungi`/`/banlist_rimuovi` call `ArtisanService.reload_banlist()`, which invalidates the
   shared module cache (`invalidate_banlist_cache()`) so both instances reload on the next validation —
   no restart needed.
3. Fetch card data from Scryfall (`POST /cards/collection`, batches of 75), checking the SQLite-backed
   cache (`cached_cards` table, loaded into the in-memory `_card_cache` dict at startup) first.
4. Determine Artisan legality per card: SPG rarity override (`arena_overrides.py`) first, then the
   cached `artisan_legal` flag if not stale (`is_artisan_legal_stale()`, 30-day TTL via
   `artisan_legal_checked_at` — entries cached before the TTL existed count as stale), then a live
   `prints_search_uri + game:arena` lookup (excluding `alchemy` set_type prints), caching the result with
   `mark_artisan_legal()`. Admin `/invalidate_card_cache <carta>` forces a full re-check of one card
   without waiting for the TTL. The SPG override table itself refreshes automatically every 7 days
   (`periodic_spg_refresh_loop()`) — `update_spg_overrides()` is incremental (`checked_cards` per set
   code, not the old "whole set done forever" `processed_sets` flag that used to make every run after the
   first a silent no-op), so repeated/scheduled calls only cost the cards that are new since last time.
   Admin `/forced_rarity_refresh` triggers the same check immediately instead of waiting for the weekly
   run.
5. Validate mainboard ≥ 60 / sideboard ≤ 15 counts.
6. On success, generate a showcase PNG (`DeckImageGenerator`) and post embeds to the log/deck channels.

Scryfall calls are serialized through an `asyncio.Semaphore(1)` with a ~110ms delay and exponential
backoff retry on HTTP 429. The card cache (`utils/card_cache.py`) persists to the `cached_cards` SQLite
table with incremental UPSERT/DELETE (`save_cache()`, tracking dirty card names — not a full-table
rewrite) every 60s via `periodic_save_loop()`; `load_cache()` is called once from
`database/engine.py:init_db()`, not per `ArtisanService` instance. `data/card_cache.json` (the pre-Step-4
format) is no longer read or written once the table is populated — it's migrated once automatically if
found on an empty table, then left inert on disk (gitignored, no longer tracked). The rarity-override
cache (`data/arena_rarity_data.json`, `utils/arena_overrides.py`) is unrelated and still file-backed with
atomic `.tmp` + `os.replace()` writes — only the card cache moved to SQLite.

### Tournament lifecycle

`TournamentService` + `PairingEngine` + `StandingsCalculator` (`services/`) implement Swiss pairing:
create → register players (`/iscriviti`, no deck required — `TournamentPlayer.deck_name` stays `None`)
→ players submit/resubmit a validated deck separately (`/invia_deck` → `submit_deck()`, repeatable while
the tournament is still in `REGISTRATION`) → start (`start_tournament()` refuses if any active registered
player still has `deck_name is None`, round 1 random pairing) → submit results per round → generate next
round (Swiss pairing, anti-rematch) → on final round, conclude and update Glicko-2 ratings
(`services/rating.py`) for all participants. Round count is derived from player count via
`PairingEngine.calculate_rounds()`. Covered end-to-end by `tests/tournament/test_tournament_service.py`
against an isolated SQLite DB (no mocks) — registration and deck submission were split into two separate
steps/commands deliberately (previously `/iscriviti` opened a deck-validation modal directly), so a
tournament can open registration before every player has a deck ready.

### Note on `cogs/tournament/` vs `cogs/deck_validation/`

The package was renamed from `tournament` to `deck_validation` (see `CHANGELOG.md` 1.3.1) to
disambiguate it from `cogs/tournament_system/`. `README.md`'s project-structure diagram still shows the
old `tournament/` name — treat `deck_validation/` (actual directory) as current.

### Legacy code

`legacy/` holds the bot's original implementation, kept for historical reference only. It is not
imported by `main.py` and should not be modified as part of feature work.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `Tdavide04/ClepshydraBot` (uses the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary (label string equals role name): `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
