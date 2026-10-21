# Roadmap — Project Structure

Plan to reorganize the code by feature, now that the bot is a helper with three independent features
(deck validation, onboarding, Wizards monitors) plus the disabled tournament system (ADR-0004). It replaces
the September–October 2026 technical-debt roadmap: every step of that one shipped, and its history lives in
`CHANGELOG.md` (1.4.0 – 4.0.0). CHANGELOG entries up to 4.0.0 cite that roadmap's step numbers: read it with
`git show cd03992:docs/roadmap.md`.

Branch: `feature/project-structure`, cut from `main` at 4.0.0. The event calendar redesign
(`feature/event-calendar`) starts after this branch is merged.

## Why

Facts established from the code at 4.0.0:

- **The documented layering doesn't match the code.** `CLAUDE.md` says Cogs → Services → Repositories →
  Database, but `services/` holds only the disabled tournament code. The services of the active features
  live inside the cogs (`cogs/deck_validation/service.py`, `cogs/presentation/service.py`), and
  `cogs/deck_validation/__init__.py` calls `get_session()` directly for the banlist commands.
- **`utils/` is a mixed bag.** Of its 12 modules, only `console`, `permissions`, `interaction_errors` and part
  of `sitemap_monitor` are cross-cutting. The rest are whole features: both monitors, both image generators,
  the card cache, the SPG overrides, and two tournament modules.
- **Two conventions at once.** `cogs/presentation/` is already organized by feature (cog, service,
  validators, models, views), while tournaments are split by layer across `cogs/`, `services/`,
  `repositories/` and `utils/`.
- **`data/arena_rarity_data.json` is tracked in git and rewritten by the bot in production.** It blocked
  the `git pull` of the 4.0.0 deploy (same content, different whitespace).

Package by feature keeps a change to one feature inside one folder, with the layers still present inside it.
The disabled tournament code moves as a block and stops being mixed into shared folders.

## Target layout

```
main.py
config/config.py
database/                 unchanged: one schema, engine, _SCHEMA_MIGRATIONS
core/                     cross-cutting only
  console.py              log()
  permissions.py          is_admin
  interaction_errors.py   ReportingModal / ReportingView
  json_state.py           load_json_state / save_json_state (from sitemap_monitor)
  results.py              ServiceResult / ResultKind
  repository_base.py      BaseRepository
  error_handler.py        extension: tree.on_error
  logger.py               extension: log channel
features/
  deck_validation/        cog.py, service.py, validators.py, models.py, embeds.py, image.py,
                          banlist_repository.py, card_cache.py, arena_overrides.py, spg_cog.py
  onboarding/             cog.py, modals.py, views.py, service.py, validators.py, models.py, embeds.py
  monitors/               sitemap.py, event_schedule.py, ban_announcement.py, calendar_image.py,
                          event_schedule_cog.py, ban_announcement_cog.py
  tournaments/            cog.py, service.py, pairing_engine.py, rating.py, standings.py, repository.py,
                          user_repository.py, embeds.py, logic.py
seeds/                    tracked starting data: banlist.txt, arena_rarity.json (since 4.0.2)
data/                     runtime state, ignored by git
tests/                    mirrors features/ and core/
```

Checked before choosing it:

- Every runtime path (`data/...`, `assets/...`) is relative to the working directory, not to `__file__`,
  so moving a module doesn't move the files it reads.
- `main.py` stays the entry point, so the pm2 process doesn't change.
- The only cross-feature import is the tournament cog using `ArtisanService` from deck validation. It stays,
  as a dependency of a disabled feature on an active one, never the reverse.

## Rules for every step

1. One approved step = one commit. Each step ends with `python -m pytest`, `python -m ruff check .` and
   `python -m ruff format --check .` green, so the branch works after every commit.
2. A move step only moves code: `git mv` plus import rewrites, no behaviour change. A behaviour change is its
   own step with a test first (ADR-0002).
3. Cog changes are verified by hand under `TEST_MODE=True`, and the CHANGELOG entry says what was checked.
4. Every doc whose description a step makes stale is updated in that step.
5. Version bumps follow the table in `CLAUDE.md`. The restructure (phase 2) is one mechanical point: several
   commits, a single CHANGELOG entry and a single bump, in its last commit.

Status of each step: `todo` → `in progress` → `done`.

---

# Phase 0 — This roadmap

## Step 0 — Replace the old roadmap

**Status:** done (2026-10-21) · `docs` · shipped in 4.0.1

The ADRs and topic docs cite old step numbers ("roadmap step 11", "Step 4 of `docs/roadmap.md`"). Rewrite
each citation to the CHANGELOG version that shipped it, so no doc points to a step that no longer exists.
The branch rule in `CLAUDE.md` (work on `feature/<topic>`, PR to `main`) lands in the same commit.

# Phase 1 — Fixes before the move

Small behaviour fixes, done first so they don't get lost inside a large diff.

## Step 1 — `/presentati`: the Annulla button and raw error text

**Status:** done (2026-10-21, 4.0.1) · `fix(onboarding)` · PATCH

- `PreviewView` never sets `self.message`, so **Annulla** raises `AttributeError` after it has already
  replied. Seen in production on 2026-10-20. Since 4.0.0 `ReportingView` catches it, and the user gets
  "Presentazione annullata" followed by the generic error message.
- `_on_confirm` catches every exception and shows the user the raw text (`❌ Errore: {e}`), bypassing
  `ReportingView`: staff get no log and the user sees internal details.
- Found while fixing it: on an invalid presentation, or with the presentation channel missing, the member
  got "Benvenuto tra i Planeswalker!" anyway. `publish()` now returns a `ServiceResult` (tested in
  `tests/onboarding/`).

Verification: service tests, plus the two buttons by hand under `TEST_MODE=True`. Docs: `docs/onboarding.md`.

## Step 2 — Seeds in `seeds/`, runtime state out of git

**Status:** done (2026-10-21, 4.0.2) · `fix(cache)` · PATCH

`data/arena_rarity_data.json` holds `overrides` (cards whose Arena rarity differs from paper) and
`checked_cards` (SPG scan progress). `update_spg_overrides()` writes both in production, and nobody edits it
by hand (confirmed by the user, 2026-10-21), so it was runtime state that happened to be tracked.

- The tracked content moved to `seeds/arena_rarity.json`, and the runtime file is ignored by git. The loader
  reads the runtime file, or the seed while it doesn't exist, **without copying**: an earlier draft copied
  the seed on load, and the deck validation tests then wrote the real `data/` file. The first SPG scan
  (at every start) creates the runtime file.
- `cards.txt` moved to `seeds/banlist.txt`. It was already a seed: `import_from_file()` reads it only when
  `banned_cards` is empty. `docs/banlist-system.md` now says the DB is authoritative and the seed may be
  older. The dead `load_banlist()` / `BANLIST_PATH` in `validators.py` went with it, since they named the
  old path.
- Changed from the plan: the folder is `seeds/` at the root, not `data/seeds/`. `data/` is excluded from
  the Docker image (`.dockerignore`) and mounted as a volume, so a seed under it would never reach the
  container. `cards.txt` worked in Docker only because it was at the root. Docker was removed right after
  (step 2a); `seeds/` stays, to keep tracked data apart from `data/`.

Deploy caveat: the pull that removes the runtime file from git also deletes it on the VM, so the 4.0.2
deploy backs it up before the pull and restores it before the restart (`docs/infrastructure.md`).

## Step 2a — Remove the unused deploy alternatives

**Status:** done (2026-10-21) · `build` · no bump

Added during this phase, after step 2 showed Docker still shaping decisions. Production runs under `pm2`, so
the Docker setup (never built by CI) and `deploy/clepshydrabot.service` (never installed, wrong paths) are
gone, with their docs. Checking the unit showed that pm2 had no boot service on the VM: `pm2 startup` and
`pm2 save` were run there, so the bot now comes back after a reboot. Rationale and the way back:
`docs/adr/0005-unused-deploy-alternatives-removed.md`.

---

# Phase 2 — Restructure by feature

One point: commits 3–9, one CHANGELOG entry and one bump in step 9.

## Step 3 — Safety net and an explicit extension list

**Status:** done (2026-10-21) · `refactor` · bump with step 9

Cogs have no tests, so a broken import after a move would show up only at startup in production. Before
moving anything:

- add a test that imports every application module and checks that each extension has a `setup()`;
- replace the `os.listdir("./cogs")` scan in `setup_hook` with an explicit `EXTENSIONS` list, keeping
  `DISABLED_COGS`. The scan depends on the folder layout this phase changes, and an explicit list makes
  "which features are on" readable in one place.

Done as `tests/core/test_extensions.py`. `main.py` had to stop starting the bot at import time to be
importable (`main()` behind `if __name__ == "__main__"`; pm2 runs `python main.py`, so nothing changes in
production). `DISABLED_COGS` now holds full module paths (`"cogs.tournament_system"`). A stubbed
`setup_hook()` run loads the same 7 cogs and 9 slash commands as 4.0.0.

## Step 4 — `core/`

**Status:** done (2026-10-21) · `refactor` · bump with step 9

Move the cross-cutting modules listed in the target layout. Split `load_json_state` / `save_json_state` out
of `sitemap_monitor`, because `arena_overrides` uses them and isn't a sitemap monitor.

Done with `git mv` and import rewrites only. `sitemap_monitor` no longer re-exports `log`: the monitors
import it from `core.console`. The JSON state and console log tests moved to `tests/core/` with
`test_interaction_errors.py`. CI coverage now includes `core`. A stubbed `setup_hook()` loads the same 7 cogs
and 9 commands, the logger and error handler now as `core.logger` and `core.error_handler`.

## Step 5 — `features/monitors/`

**Status:** done (2026-10-21) · `refactor(monitor)` · bump with step 9

Event schedule, ban announcement, sitemap helpers, the calendar image generator and their two cogs. Goes
first among the features because the calendar redesign comes next. `MONTHS_IT`, shared by the ban
announcement and the calendar image, stays in `event_schedule.py`.

Done: `sitemap.py`, `event_schedule.py`, `ban_announcement.py`, `calendar_image.py`, `event_schedule_cog.py`,
`ban_announcement_cog.py` (from `utils/` and `cogs/`), tests in `tests/monitors/`. Module names lost their
redundant prefixes and suffixes (`arena_`, `_monitor`, `_generator`, `_updater`); class names (cogs
included) are unchanged, so `get_cog()` lookups and the log channel are unaffected.

## Step 6 — `features/deck_validation/`

**Status:** todo · `refactor(deck)`

The current `cogs/deck_validation/` package plus the deck image generator, the card cache, the SPG overrides,
the banlist repository and `spg_override_updater` (`/forced_rarity_refresh`, `/invalidate_card_cache`).

## Step 7 — `features/onboarding/`

**Status:** todo · `refactor(onboarding)`

`cogs/presentation/` renamed to match its topic doc (`docs/onboarding.md`) and its commit scope.

## Step 8 — `features/tournaments/`

**Status:** todo · `refactor(tournament)`

The disabled feature as one block: cog, service, pairing, rating, standings, repositories,
`tournament_embeds` and `tournament_logic`. It stays in `DISABLED_COGS`.

## Step 9 — Remove the old folders and update the docs

**Status:** todo · `refactor` · PATCH for the whole phase

- Delete the empty `cogs/`, `services/`, `repositories/` and `utils/`.
- Update the CI `--cov` paths, plus the `CLAUDE.md` architecture map, layering and invariants (the
  "inside `utils/`" config-import rule becomes a rule for `core/` and `features/`).
- Update `docs/architecture.md`, the topic docs' paths, the "Line" column of `docs/commands.md`, and the
  README repository structure.
- CHANGELOG entry and version bump.

---

# Phase 3 — Layering fixes inside the features

## Step 10 — Banlist commands through a service

**Status:** todo · `refactor(banlist)` · PATCH

`/banlist`, `/banlist_aggiungi` and `/banlist_rimuovi` open a DB session in the cog. Move that into service
methods returning `ServiceResult`, test first, and keep the `reload_banlist()` invalidation in one place.

## Step 11 — Root configuration (optional)

**Status:** todo · `build` + `ci` · no bump

- Move the `ruff.toml` and `pytest.ini` settings, plus the coverage config, into one `pyproject.toml`. This
  is tidiness only: the bot runs as `python main.py`, so the `src/` layout that PyPA recommends for
  distributed packages brings nothing here.
- Point both CI jobs at `.python-version` (`python-version-file`) instead of hardcoding `3.12` twice, so the
  version has one owner besides ruff's `target-version`.
- `requirements*.txt` stay: for a deployed application with pinned versions they are the right tool, and
  pip and CI already read them.

---

# Backlog (not scheduled)

- **English slash command names** (ADR-0003). To be decided in a dedicated session.
- **Event calendar image redesign**, on `feature/event-calendar` after this roadmap.
- **Onboarding state is in memory** (`PRESENTATION_DATA_STORE`): a restart mid-presentation loses it.
  Acceptable for now, documented in `docs/onboarding.md`.
- **Coverage threshold in CI.** None yet; reconsider once the cogs are thinner.

# Decisions (2026-10-21)

- Step 2: the override file is written only by the SPG scan, so it stops being tracked (seed + runtime file).
- Folder names: `features/` and `core/`, with `presentation` renamed to `onboarding`.
- Versions: steps 1 and 2 as 4.0.1 and 4.0.2, the whole of phase 2 as one PATCH (4.0.3), step 10 as 4.0.4.
- This work stays on its own branch, `feature/project-structure`, separate from `feature/event-calendar`.
