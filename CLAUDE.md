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

Suite: 165 tests total, no `pytest-asyncio` — async integration tests
(`tests/tournament/test_tournament_service.py`, `tests/deck_validation/test_artisan_service.py`,
`tests/deck_validation/test_card_cache.py`, `tests/deck_validation/test_arena_overrides.py`,
`tests/utils/test_arena_event_schedule.py`, `tests/utils/test_ban_announcement.py`) instead
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
  `send_log(level, event, info)` on, to post colored embeds to a central log channel — `send_log()` also
  takes optional `fields` (list of `{"name", "value", "inline"}`, added as separate embed fields) and
  `files` (list of `discord.File`, attached to the same message) kwargs, used by the Arena Event Schedule
  monitor to attach calendar images (see below).
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
  (SPG rarity overrides), `arena_event_schedule.py` (monitors Wizards' "[Set] MTG Arena Event Schedule"
  pages via the site's `sitemap.xml`, see below), `event_calendar_image_generator.py` (Pillow-based
  calendar image for the Event Schedule, see below), `ban_announcement.py` (monitors Wizards' "Banned and
  Restricted Announcement" posts via the same `sitemap.xml`, notify-only — see below),
  `deck_image_generator.py` (Pillow-based deck showcase PNGs), `permissions.py` (`@is_admin()` app-command
  check based on a configured Discord role name), `tournament_embeds.py`, `tournament_logic.py`.

### Config and environment

`config/config.py` loads `.env` via `python-dotenv` and reads all settings as module-level constants
(no pydantic/settings class). `TEST_MODE` selects `_TEST`-suffixed env vars (token, guild, channels, db
path) at import time — there is no runtime toggle. `main.py` constructs the bot, calls `init_db()`,
dynamically loads every module/package under `cogs/`, syncs the slash command tree to a single guild
(`GUILD_ID`) rather than globally, logs `SYSTEM_STARTUP` to Discord, and only THEN starts four background
tasks — `periodic_save_loop()` (card cache autosave, every 60s), `periodic_spg_refresh_loop()` (SPG rarity
override auto-refresh, every 7 days — see below), `periodic_event_schedule_check_loop()` (Arena Event
Schedule page monitor, every 24h — see below), and `periodic_ban_announcement_check_loop()` (Banned and
Restricted Announcement monitor, every 24h — see below). The four `self.loop.create_task(...)` calls must
stay AFTER the sync+log block, not before: `create_task` only schedules, it doesn't block, so if scheduled
earlier the background tasks' first runs (both do real HTTP calls, not instant) can race ahead of and
finish before the `await self.tree.sync(...)` call resolves — observed in production, the `SYSTEM_STARTUP`
log arrived *after* the automatic check logs instead of before. Startup failures (`discord.LoginFailure`
and other exceptions in `setup_hook`/`bot.run`) are caught, logged to stderr with a `FATAL:` prefix, and
exit non-zero instead of failing silently — this also means a broken slash-command definition (e.g. a
description over Discord's 100-char limit) crashes the whole bot on every restart, not just that one
command, since `tree.sync()` fails for the entire batch.

`VERSION` (shown in the `SYSTEM_STARTUP` Discord log) is a hardcoded constant in `config/config.py`, not
an env var — bump it by hand in the same commit that bumps `CHANGELOG.md`. From 3.0.0 onward: bump MINOR
for a new feature, PATCH for a bug fix (see "Versioning" at the top of `CHANGELOG.md`).

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
   Unevaluated cards' prints are fetched in batches of 25 via a combined Scryfall query
   (`_fetch_prints_by_oracle_ids()`, `q=oracleid:X or oracleid:Y or ...`) instead of one
   `prints_search_uri` request per card — the first full-set scan after the `processed_sets` →
   `checked_cards` migration had to re-check ~175 cards at once and triggered a storm of 429s under the
   old one-request-per-card design (observed in production). The oracle_id list is always deduplicated
   before building the query: the upstream `set:spg unique=prints` search lists one row per *printing*,
   so a card with several SPG printings appears more than once, and a query with repeated `oracleid:`
   terms was verified live to make Scryfall silently drop some cards from the results instead of erroring.
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

### Arena Event Schedule monitor

`utils/arena_event_schedule.py` watches Wizards' per-set "[Set] MTG Arena Event Schedule" pages (e.g.
`the-hobbit-event-schedule`) — distinct from the weekly "MTG Arena Announcements" posts, published once
per expansion (~6-9 weeks) and updated in place by Wizards during the set's lifecycle rather than being a
one-off snapshot. Wizards does not remove past sets' pages from the sitemap, so at any given time several
of them coexist there — `check_event_schedule_updates()` only cares about the one with the most recent
`lastmod` (`_pick_latest()`, plain lexicographic max since the timestamps are fixed-width ISO-8601), i.e.
the currently active set; without this filter, the first run on a fresh machine (empty state) would report
every still-listed page as "new" at once (observed in production: 4 pages flooding the log channel
simultaneously). Since there is no official API/RSS, `check_event_schedule_updates()` fetches
`magic.wizards.com/en/sitemap.xml` (standard XML sitemap with `<lastmod>` per URL) every 24h
(`periodic_event_schedule_check_loop()`, cheap check — a single static-file GET), and only fetches+parses
the latest event-schedule page when its `lastmod` changed versus `data/arena_event_schedule_state.json`
(`{latest_url, latest_lastmod}`, not tracked in git, pure bookkeeping — contrast with
`arena_rarity_data.json`, which holds curated data and is tracked). The 24h cadence is
deliberately much tighter than the ~6-9 week content cadence: the sitemap check itself is nearly free, so
polling often lowers notification latency without adding cost, while the fragile part (HTML parsing) only
ever runs on an actual change. `parse_full_event_calendar()` extracts the page's "Full Event Calendar"
section (real structured HTML — `<h2>/<h3>/<h4>Category</h2>` + `<ul><li>...</li></ul>` blocks, bounded
between that heading and the next `</article>`) and returns `None` if the expected structure isn't found,
so a site redesign produces a `WARN` Discord log asking for a manual check instead of a wrong/partial
summary posted as if authoritative. Admin `/forced_event_schedule_check` forces an immediate re-check of
the current latest page, ignoring the saved `lastmod`.

`send_event_schedule_log()` posts a calendar **image** per month, not text: each category entry (e.g.
`"August 11-19: Duskmourn: House of Horror"`) is parsed by `parse_event_entry()` into a date range, and
`build_month_calendar()` groups entries into `{(year, month): {category: [(day_start, day_end, name)]}}`,
splitting any range crossing a month boundary into one clipped segment per month it touches. Missing year
is inferred from the current date (`_infer_start_year()` — if a range's start month is more than ~6 months
"behind" the current month, it's assumed to be next year, to handle a page published near year-end
referencing January). `utils/event_calendar_image_generator.py`'s `EventCalendarImageGenerator` then
renders each `(year, month)` as a Gantt (one row per category, colored by *family* — Premier Draft/Quick
Draft/Flashback/Sealed & Cube/Metagame/Community, a keyword heuristic on the category name in
`_classify_family()`, not data from the Wizards page) plus a detailed text list below it (full event
names, no truncation, category shown in parentheses) — this two-part layout is the result of several
design iterations against real data: a plain day-grid calendar is unreadable because long-running
categories (Premier Draft, Sealed...) repeat identically across dozens of day cells; a family-only Gantt
(6 rows) loses the "is this really two distinct queues or one drawn twice" signal a reader wants; the
final design keeps one row per category (so nothing is silently merged) but relies on the text list below
for anything a bar is too narrow to show a name for. `_clean_name()` strips the redundant
`"Magic: The Gathering | "` and `"Arena Direct for "` prefixes from event names before rendering, since
the row's family color already conveys the category. `create_month_panel()` (an earlier per-category
Gantt with no family grouping) and `create_multi_month_calendar()` (stitches several months' panels plus
ONE merged detail list into a single image) both remain in the module, unused by the current flow, kept
in case that layout is wanted again.

`send_event_schedule_log()` uses this to attach one `discord.File` image per month to a single Discord
log message (via `Logger.send_log()`'s `files` kwarg) — used by both the automatic daily check and
`/forced_event_schedule_check`, so both now post images instead of the field-per-category embeds used
before 3.2.0. If the page's categories were parsed but none of their entries match the expected date
format, `build_month_calendar()` returns empty and a dedicated `WARN` (`ARENA_EVENT_SCHEDULE_NO_DATES`) is
logged instead of generating an empty image. Admin `/preview_calendario_eventi` (separate from
`/forced_event_schedule_check`) re-runs the same check and posts the images as a normal (non-ephemeral)
message in the invoking channel, without touching the log channel — a manual preview tool, not wired into
`send_event_schedule_log()`.

### Banned and Restricted Announcement monitor

`utils/ban_announcement.py` watches Wizards' "Banned and Restricted Announcement" posts
(`magic.wizards.com/en/news/announcements/banned-and-restricted-*`), published on a fixed cadence
(roughly every 6 weeks, always on a Monday) covering all official constructed formats (Standard, Pioneer,
Modern, Legacy, Vintage, Pauper, Alchemy, Historic, Timeless, Brawl, Competitive Brawl) — notably, none of
these is the Artisan homebrew format this community's own banlist governs (see "Sistema Banlist" above /
`docs/banlist-system.md`), so this monitor is **notification-only**: it never writes to `banned_cards`.
Structurally it reuses the same pattern as the Arena Event Schedule monitor — these announcement pages are
also listed in `magic.wizards.com/en/sitemap.xml` with `<lastmod>`, Wizards doesn't remove past ones, so
only the most recent by `lastmod` is considered (`_pick_latest()`), and the cheap sitemap check runs daily
while the page itself is only fetched+parsed on a `lastmod` change (`check_ban_announcement_updates()`).

Unlike the Event Schedule page, an announcement is free-form prose per format, not a structured date list
— but each `<h2>Format</h2>` section is followed by a reliable one-paragraph summary
(`<p style="padding-left: 30px;">Card X is banned.<br/>Card Y is unbanned.</p>`, or literally "No changes"
when nothing changed in that format), verified live against the August/June/March 2026 announcements.
`parse_ban_announcement()` extracts only that summary paragraph per format — never the surrounding
analysis prose or sample decklists, both too unstructured to parse reliably and out of scope for a
notify-only bot — and drops any format whose summary is "No changes", so the result dict only lists
formats that actually changed. An announcement parsed correctly but with nothing to report (all formats
unchanged) is a valid `{}` result (`BAN_ANNOUNCEMENT_NO_CHANGES` INFO log), distinct from `None` (no `<h2>`
summary structure found at all — `BAN_ANNOUNCEMENT_UNPARSEABLE` WARN, same "ask for a manual check instead
of guessing" philosophy as `parse_full_event_calendar()`). When there are real changes,
`send_ban_announcement_log()` posts one Discord embed field per affected format (via `Logger.send_log()`'s
`fields` kwarg), each field's value being the format's change lines — plus a note in the message body that
the bot's own Artisan banlist was **not** touched. Admin `/forced_ban_announcement_check` forces an
immediate re-check of the current latest announcement, ignoring the saved `lastmod` — mirrors
`/forced_event_schedule_check`, no equivalent of `/preview_calendario_eventi` here since there's no image
to preview.

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
