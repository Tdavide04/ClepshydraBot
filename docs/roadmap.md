# Roadmap — Technical Improvements

Work plan to fix known bugs and improve the bot's efficiency/robustness, which came out of a full codebase
review (September 2026). It doesn't replace the historical feature roadmap in `CHANGELOG.md` — it only covers
technical debt and architectural improvements.

## Starting Point (already on `feature/v2` before this roadmap)

An earlier intervention (September 9, 2026, commits `bedcbe9`/`f46f1de`/`9f4203e`) had already tackled part of
this same debt, in parallel with writing this roadmap:

- **CI**: `.github/workflows/ci.yml` — `pytest` as a blocking gate on every push/PR, `ruff` as an informative
  step (non-blocking: the codebase had pre-existing lint debt not cleared yet). Covers Step 8 below.
- **`TournamentService` tests**: `tests/tournament/test_tournament_service.py`, 10 end-to-end tests
  (registration, start, pairing, result submission, next round, forced drop, standings, rating) on an
  isolated SQLite per test, no mocks — with one `asyncio.run()` per test instead of `pytest-asyncio` (see
  `tests/tournament/conftest.py`). Covers most of Step 7.
- **Startup resilience**: `main.py` catches `discord.LoginFailure` and other startup exceptions, logs to
  stderr with the `FATAL:` prefix and exits with a non-zero code instead of failing silently.
  `deploy/clepshydrabot.service` (systemd) is available as an alternative, but it is **not the one used in
  production** — the VM uses `pm2` (see `docs/infrastructure.md`).
- A first attempt at fixing the banlist cache (`ArtisanService.reload_banlist()`), **incomplete**: reload only
  on the called instance, not on the second `ArtisanService` created by `cogs/deck_validation/__init__.py`.
  Completed in Step 1 below (cache moved to module level).

## Rule for Every Step

Every step, when implemented, **must**:

1. Change only the code listed under "Changes" (no opportunistic out-of-scope refactors).
2. Update every document listed under "Docs to update" — including those whose content becomes **obsolete**
   (e.g. a "Known Issues" section describing a bug now fixed must be removed or marked as fixed, not left to
   lie).
3. Update `README.md` if the step changes something visible there (commands, quick start, stack, repository
   structure).
4. Add a `CHANGELOG.md` entry (new version, semver: fix → patch, feature/refactor → minor) in the format
   already in use (`Added`/`Fixed`/`Changed`/`Refactored`/`Docs` sections).
5. Update `CLAUDE.md` only if information described there changes (commands, layering, behavior of a
   component it mentions).
6. Be validated: run `pytest tests/ -v` (or `python -m pytest`), and if the step touches code without tests,
   explain explicitly how it was verified by hand (never claim it "works" without proof).
7. Work on `feature/v2`, not on `main` — `main` only receives merges via PR from `feature/v2`.

Status of each step: `todo` → `in progress` → `done`.

---

## Step 0 — Refactor `docs/technical-report.md`

**Status:** done (2026-09-11)

**Problem:** the document almost entirely duplicated `docs/infrastructure.md` (infra, deployment, env,
logging) and other dedicated docs (architecture, features, cache, validation flow), becoming a second source
of truth to keep in sync by hand.

**Changes:** reduced to the "identity card" information not duplicated elsewhere: OCI instance (OCID, launch
date, IP, SSH access, process manager), hardware/OS specs, tech stack and versions, a reminder of the RAM
constraint. Removed the Repository Structure, Features, Cache, External APIs, Validation Flow,
Limitations/Technical Debt, V2 Architecture and Roadmap sections — replaced by a table of links to the
dedicated documents, this file included.

**Docs updated:** `docs/technical-report.md` (this step).

---

## Step 1 — Fix banlist cache invalidation

**Status:** done (2026-09-11)

**Problem:** `ArtisanService._banlist` (`cogs/deck_validation/service.py`) was loaded once from the DB and —
in the starting code (before any fix) — never reloaded. A first fix attempt (`reload_banlist()`, see above)
was still incomplete: the bot creates **two** separate `ArtisanService` instances
(`cogs/tournament_system/cog.py` and `cogs/deck_validation/__init__.py`), and reloading the `self._banlist`
attribute on one has no effect on the other.

**Changes:**
- `cogs/deck_validation/service.py`: `_banlist` moved from an instance attribute to a module variable
  `_banlist_cache`, shared by every `ArtisanService`. New module function `invalidate_banlist_cache()` (same
  pattern already used by `utils/arena_overrides.py` for `_override_cache`). `reload_banlist()` stays as an
  instance wrapper (no change at the call sites in `cogs/tournament_system/cog.py`), but now invalidates the
  shared cache instead of its own attribute only.

**Docs updated:**
- `docs/banlist-system.md` — §5, §10, "Known Issues" item 2.
- `docs/caching.md` — §4 "Banlist Cache", "Cache Summary" table.
- `CHANGELOG.md`.

**Validation:** `pytest tests/ -v` — 88 tests, all passing. No automated test covered the banlist/DB path with
two `ArtisanService` instances in parallel yet (planned as an extension of Step 7). Verified by hand by reading
the flow: both cogs create `ArtisanService(bot)` in `__init__`, and since this change both instances
read/write the same module `_banlist_cache` — an invalidation called from either one is visible to the other
on the next `validate_deck()`.

---

## Step 2 — Explicit handling of schema migrations

**Status:** done (2026-09-11)

**Problem:** `database/engine.py:_migrate_schema()` wraps every `ALTER TABLE` in `try/except Exception: pass`
(8 occurrences). The pattern is meant for the "column already exists" case, but it also hides real errors
(permissions, full disk, wrong column type) without a log.

**Changes:**
- `database/engine.py`: before every `ALTER TABLE`, check whether the column exists with
  `PRAGMA table_info(<table>)` instead of relying on the exception; log at `WARN`/`ERROR` (via the Logger cog
  or stdout) any unexpected exception instead of silently ignoring it.
- Remove the duplicated `import os` at the top of the file (lines 1-2).

**Docs to update:**
- `docs/database.md` — migrations section: describe the new explicit check.
- `CHANGELOG.md` — new `Fixed`/`Changed` entry.

**Validation:** `pytest tests/ -v` — 88 tests, all passing (`test_tournament_service.py` exercises
`_migrate_schema()` on every test through `init_db()`, but only in the "columns already present" case, because
the test DB is created from scratch with `Base.metadata.create_all`). To also check the real path — old schema
without the columns, an actual `ALTER TABLE`, then idempotency on a re-run — a SQLite DB with the "old" schema
(tables without the migrated columns) was built by hand with a temporary script, and `_migrate_schema()` was
run twice in a row: the first run adds all 8 columns (confirmed by reading `PRAGMA table_info` for each table
afterwards), the second produces neither errors nor redundant ALTERs. Script removed after the check, not in
the repository.

---

## Step 3 — Invalidation/TTL for `artisan_legal` in the card cache

**Status:** done (2026-09-11)

**Problem:** the `artisan_legal` field in `data/card_cache.json` (`utils/card_cache.py`) never expires. If a
card becomes legal/illegal in Artisan after a new Arena printing, the bot keeps using the value computed on the
first check, with no way to fix it short of editing the JSON by hand.

**Changes:**
- `utils/card_cache.py`: add a per-entry timestamp (e.g. `checked_at`) and a configurable TTL (proposed: 30
  days) past which `_is_arena_artisan_legal()` (in `cogs/deck_validation/service.py`) re-checks the card
  instead of trusting the cache.
- Consider a targeted admin invalidation command (`/invalidate_card_cache <carta>`), similar to
  `/update_spg_overrides` (since renamed `/forced_rarity_refresh`), to fix single cards without waiting for
  the TTL.

**Docs to update:**
- `docs/caching.md` — "Scryfall Card Cache" section: add the TTL and the new command.
- `docs/deck-validation.md` — item 4 "Arena Legality Check": update the order of the checks.
- `docs/commands.md` — if the new admin command is added.
- `CHANGELOG.md` — new `Added`/`Fixed` entry.

**Actual implementation:** 30-day TTL (`ARTISAN_LEGAL_TTL_DAYS`), timestamp stored as ISO 8601 UTC
(`artisan_legal_checked_at`). Entries cached before this change don't have the field → treated as stale
(fail-open toward a re-check, not toward unlimited trust). Also added `/invalidate_card_cache <carta>` (admin,
in `cogs/spg_override_updater.py` next to `/update_spg_overrides`) to fix single cards without waiting for the
TTL — it removes the whole entry, not just the flag, so the base data is fetched again too. The per-process
in-memory cache (`_ARENA_LEGAL_CACHE`, keyed by `oracle_id`) is **not** subject to the TTL: it resets on every
bot restart anyway, so the staleness risk there is lower and stays out of scope for this step.

**Validation:** `pytest tests/ -v` — 88/88 green (no existing test covered `card_cache.py` or
`ArtisanService`, unchanged). A temporary manual script (removed after the check, not in the repository)
verified: entry without a timestamp → stale; freshly marked entry → not stale; entry older than 30 days →
stale; entry within 30 days → not stale; malformed timestamp → stale (fail-open); `invalidate_card()` removes
an existing entry and returns `False` if already absent.

---

## Step 4 — Card cache: from JSON to an SQLite table

**Status:** done (2026-09-11)

**Problem:** `save_cache()` rewrites the whole `data/card_cache.json` every 60s if `_dirty`, even for a single
modified card. The cache grows with no cleanup (no size limit) — on a 1 GB RAM VM, periodically rewriting an
ever-growing file in full wastes I/O and memory compared with an incremental write. The file is also tracked in
git (2.2 MB, grown over 8 commits with no historical value) — to be evaluated whether to stop tracking it
regardless of this step.

**Changes:**
- `database/models.py`: new `CachedCard` model (or similar) in the same SQLite instance already in use.
- `utils/card_cache.py`: replace the JSON backend with SQLAlchemy queries (incremental get/set); remove
  `periodic_save_loop()` if no longer needed (writes become direct).
- `main.py`: remove the task startup if eliminated.
- One-off migration of the existing data from `data/card_cache.json` to the new table, after which the file can
  be deleted from `data/` and untracked from git.

**Docs to update:**
- `docs/caching.md` — rewrite the whole "Scryfall Card Cache" section.
- `docs/database.md` — add the new table to the schema.
- `docs/architecture.md` — architecture diagram (remove `card_cache.json` as separate storage).
- `CLAUDE.md` — utils/caching section.
- `CHANGELOG.md` — new `Changed`/`Refactored` entry.

**Note:** higher-risk step than the others (it touches the DB schema and a component used by every deck
validation) — to be done after Step 7 (`ArtisanService` tests), not before, so it is validated with real tests
rather than by eye.

**Actual implementation (design discussed before writing code):** instead of making the whole cache `async`
(it would have meant propagating `await` to ~15 places in `cogs/deck_validation/service.py`), only the
persistence layer changed:
- `get_cached_card()`/`set_cached_card()` stay **synchronous** and work on the in-memory `_card_cache` dict
  exactly as before — zero changes to `validate_deck()`'s hot path.
- `save_cache()` tracks `_dirty_upserts`/`_dirty_deletes` (two `set[str]` of card names) instead of a global
  boolean flag, and writes to SQLite only the changed entries (targeted UPSERT/DELETE), not the whole dict.
- `load_cache()` became `async` and moved from "called in `ArtisanService.__init__()`" (once per instance, so
  in theory several times per process) to "called once in `database/engine.py:init_db()`", next to
  `_migrate_banlist()`/`_migrate_schema()` — loading the cache is a bot startup concern, not a per-instance
  one.
- One-off migration: if `cached_cards` is empty and `data/card_cache.json` still exists, `load_cache()`
  imports everything in a single transaction.
- `data/card_cache.json` untracked from git (`git rm --cached`) and added to `.gitignore`; it stays on the
  local disk as an inert file (no longer read or written by the bot once the table is populated).
- `periodic_save_loop()` unchanged in form (it still calls `save_cache()` every 60s), only what `save_cache()`
  does internally changes.

**Validation:** `python -m pytest tests/ -v` — 101/101 green (93 → 101, +8 new direct tests on
`utils/card_cache.py` in `tests/deck_validation/test_card_cache.py`: loading with an empty table, legacy
migration, incremental upsert, no-op without changes, update of an existing row, invalidation with a delete on
the next save, invalidation of an entry never persisted (no error), reload after a simulated "restart"). Plus a
targeted manual check against the repository's real `data/card_cache.json` (407 entries, 2.2MB, double-faced
cards included): complete migration, data identical byte for byte on a sample, no duplicate rows on a second
simulated "restart" — temporary script, removed after the check, not in the repository.

---

## Step 5 — Reduce N+1 queries in `TournamentService._update_ratings`

**Status:** done (2026-09-11)

**Problem:** `services/tournament_service.py:_update_ratings()` loads every `User` with a separate
`session.get(User, tp.user_id)` inside a loop over the players, instead of a single batch query. Negligible
impact today (tournaments of a few dozen people), but it doesn't scale.

**Changes:**
- `services/tournament_service.py`: replace the `session.get` loop with a single
  `select(User).where(User.id.in_(user_ids))` query.

**Docs to update:**
- `docs/tournaments.md` — if it describes the rating update flow, update the reference to the implementation.
- `CHANGELOG.md` — new `Changed` (performance) entry.

**Validation:** `pytest tests/ -v` — 88/88 green, including `test_tournament_completes_and_updates_rating`,
which exercises `_update_ratings()` end to end against real SQLite (not just a compile check).
`docs/tournaments.md` doesn't describe `_update_ratings()`'s implementation details (only the name in the
methods table), so it needed no update.

---

## Step 6 — Uniform DB session handling

**Status:** done (2026-09-11)

**Problem:** every `TournamentService` method (and those of the other service classes) repeats
`session, repo... = self._get_repos()` followed by `try/finally: await session.close()` by hand. Correct but
verbose and easy to forget in new methods.

**Changes:**
- `services/tournament_service.py` (and any other service with the same pattern): introduce a context manager
  (`async with self._session() as (repo1, repo2, ...):`) centralizing session open/close, without changing the
  business logic of the individual methods.

**Docs to update:**
- `CHANGELOG.md` — new `Refactored` entry.
- `docs/architecture.md` and `CLAUDE.md` didn't describe `_get_repos()` in detail: no change needed.

**Validation:** `pytest tests/ -v` — 88/88 green. `test_tournament_service.py` exercises almost every public
`TournamentService` method (registration, start, pairing, result submission, next round, forced drop,
standings, rating), so it acted as a real safety net for the refactor, not just a compile check. Diff checked
by hand line by line: every method turns `session, repo... = self._get_repos(); try: ...; finally: await
session.close()` into `async with self._repos() as (session, repo, ...): ...` without touching the logic
inside.

---

## Step 7 — Tests for `ArtisanService` (complete deck validation coverage)

**Status:** done (2026-09-11) — `TournamentService` already covered (see "Starting Point")

**Problem:** `ArtisanService.validate_deck()` — banlist + Scryfall fetch + Artisan rarity + SPG overrides — has
no coverage, unlike `TournamentService`, which now has 10 end-to-end tests.

**Changes:**
- `tests/deck_validation/test_artisan_service.py`: tests with a mocked Scryfall client (no real network calls)
  for `validate_deck()`, following the approach already used in `tests/tournament/test_tournament_service.py`
  (isolated SQLite DB per test via fixture, no new dependency — no `pytest-asyncio`, reusing the
  `asyncio.run()` pattern of `tests/tournament/test_tournament_service.py`).
- Add a dedicated test for the banlist cache invalidation across two separate `ArtisanService` instances (the
  bug fixed in Step 1), to avoid silent regressions.

**Docs to update:**
- `CLAUDE.md` — "Commands" section (new test path), if anything relevant changes.
- `CHANGELOG.md` — new `Added` entry with the test count.

**Actual implementation:** `tests/deck_validation/test_artisan_service.py` (+ a `conftest.py` with the same env
var seeding as `tests/tournament/conftest.py`, deliberately duplicated so it stays runnable in isolation). No
`pytest-asyncio`: the same `asyncio.run()` pattern already in use. `ArtisanService._post_with_retry`/
`_get_with_retry` are replaced per instance with fake async functions (no real network call, no mock library).
5 tests:
- banned card → stop before any Scryfall call (verified by passing a `_post_with_retry` that would raise
  `KeyError` if invoked).
- valid deck (common mainboard + uncommon sideboard) → `is_valid` True.
- rare card → `illegal_rarity_cards` filled, `is_valid` False.
- **Step 1 regression**: two separate `ArtisanService` instances (as in the real bot), banlist changed through
  the first, checked through the second — it catches exactly the bug the September 9 fix had left open.
- **Step 3 regression**: a "legacy" cache entry (no `artisan_legal_checked_at`) with `artisan_legal=True`, but
  the API now reports the reprint as rare → it must be re-checked, not taken at face value.

**Validation:** `python -m pytest tests/ -v` — 93/93 green (88 existing + 5 new), run both as
`tests/deck_validation` in isolation and as part of the full suite.

---

## Step 8 — Light CI (lint + tests)

**Status:** done (2026-09-11) — partial since the "Starting Point", closed for good here

**Remaining problem:** `ruff` runs only as an informative/non-blocking step (`continue-on-error: true` in
`.github/workflows/ci.yml`), because the codebase has ~55 pre-existing lint issues not cleared yet.

**Changes (to close the step):**
- Fix the pre-existing lint issues (unused imports, multiple statements on one line, etc.) in a dedicated
  intervention, outside the scope of the functional steps above.
- Remove `continue-on-error: true` from the `lint` job in `.github/workflows/ci.yml` once clean.

**Docs to update:**
- `docs/infrastructure.md` — "Infrastructure Roadmap" section, Sprint 8: from "partial" to "done".
- `CHANGELOG.md` — new `Fixed` entry.

**Actual implementation:** 54 issues (42 outside `legacy/`, which at the time was excluded in `ruff.toml`
instead of being fixed, since it wasn't actively maintained code — the folder was later removed entirely from
the repository, see `CHANGELOG.md`). 27 fixed with `ruff check . --fix` (unused imports, f-strings without
placeholders, several imports on one line) — diff reviewed by hand before trusting the autofix. The remaining
15 by hand:
- 12 `E701` (multiple statements on one line) → split onto separate lines, no logic change.
- 2 `E712` (`TournamentPlayer.dropped == False` in `repositories/tournament_repository.py`) → ruff's suggested
  fix (`not TournamentPlayer.dropped`) was **not** applied, since for a SQLAlchemy query expression it would
  mean something different from the intent; used `.is_(False)` instead, the correct SQLAlchemy idiom for the
  same filter (it also handles NULLs correctly, unlike `==`).

Removed `continue-on-error: true` from the `lint` job in `.github/workflows/ci.yml`: it now blocks CI like
`pytest`.

**Validation:** `ruff check .` → `All checks passed!`. `pytest tests/ -v` → 108/108 green, unchanged from
before the lint cleanup (none of the fixes touched the logic).

---

## Step 9 — Containerization (Docker)

**Status:** done (2026-09-11)

**Problem:** deployment via `pm2` over manual SSH, no environment reproducibility.

**Changes:**
- Multi-stage `Dockerfile` based on `python:3.12-slim`.
- `docker-compose.yml` with a persistent volume for `data/`, `restart: unless-stopped`, `.env` mounted.

**Docs to update:**
- `docs/infrastructure.md` — "Infrastructure Roadmap" section, Sprint 7 → done; "Deployment" section with the
  Docker instructions as an additional option (without replacing the `pm2` section, which stays the method
  actually used until a migration is decided).
- `README.md` — "Quick Start" with the Docker option.
- `CHANGELOG.md` — new `Added` entry.

**Actual implementation:** multi-stage `Dockerfile` (builder with an isolated venv → non-root runtime),
`.dockerignore` (excludes `.git`, `data/`, `.env`, tests/docs/legacy — no secrets or runtime data in the
image), `docker-compose.yml` (named volume `clepshydra-data`, `env_file: .env`, `restart: unless-stopped`). It
stays an additional option: production uses `pm2`, not replaced.

**Validation:** not just writing the files — real build and run with Docker Desktop available locally.
`docker build` succeeded; `docker run` with an invalid Discord token correctly reproduces
`FATAL: ... sys.exit(1)` (the same behavior already documented for `pm2`); non-root user verified (`whoami` →
`clepshydra`) and `/app/data` writable; `docker compose up` with the same invalid token shows
`restart: unless-stopped` restarting the container automatically as expected; named volume created and
inspected. Test images/containers/volumes removed after the check, nothing left behind.

---

## Recommended Order

Step 0 → 1 → 2 → 5 → 6 → 3 → 7 → 4 → 8 → 9 — **all done**. Phase 1 complete.

Rationale: low-risk, isolated correctness fixes first (2, 5), then internal refactors with no visible behavior
change (6) — both resting on the existing `test_tournament_service.py` suite. Then the TTL invalidation (3),
which doesn't touch the schema. Step 7 (`ArtisanService` tests) is completed right before Step 4, so the card
cache migration to SQLite — the most invasive change of the list — can be validated with real tests. Closing
the `ruff` gate (8) and Docker (9) end the list: they don't fix application debt, they lower future operational
risk.

---

# Phase 2 — Development Standard (ADR-0002, ADR-0003)

Came out of the 2026-10-20 discovery (`docs/adr/0002-development-standard.md`). The same "Rule for Every Step"
of phase 1 applies, plus the standard described in `CLAUDE.md` → "Working standard".

## Step 10 — Deterministic line endings

**Status:** done (2026-10-20). Normalized 13 files stored with CRLF in the repo; the diff ignoring CRs is
empty. The files on disk, 50 CRLF plus 1 mixed, were rewritten as LF with identical content.

**Problem:** `core.autocrlf=true` without a `.gitattributes`. `git status` reported about 35 files as modified
with no real change; only line-ending differences, hiding the real changes.

**Changes:** `.gitattributes` with `* text=auto eol=lf`, plus `binary` for `*.png`, `*.db` and `*.ttf`/`*.otf`
if present. Then `git add --renormalize .` in a dedicated commit.

**Validation:** after the commit, `git status` on a clean checkout shows no modified files.

## Step 11 — Project in English (ADR-0003)

**Status:** done (2026-10-20, 3.6.5)

**Changes:** a single point, split into one commit per area, each approved before being made:
1. `refactor(lang)`: comments, docstrings, console and log-channel output, comments of the supporting files
   (`Dockerfile`, `.gitignore`, `.dockerignore` — the CI, `deploy/` and `.env.example` already had only
   English headers) — done
2. `test(lang)`: test names, comments, docstrings — done
3. `docs(lang)`: `docs/` and `README.md`, in two commits: the file renames (`git mv` + references, kept
   separate so `git log --follow` still works), then the translation — done
4. `docs(lang)`: `CLAUDE.md`, the ADRs (renamed to English), and the new `CONTEXT.md` (glossary of domain
   terms with the Italian UI words); `docs/agents/` was already in English — done

A single CHANGELOG entry and a single PATCH bump, in the last commit. What stays in Italian: strings the user
sees (command replies, modals, views, community embeds), slash command names and descriptions, past CHANGELOG
entries.

**Validation:**
- a grep for Italian function words finds nothing outside UI strings;
- pytest green and ruff clean;
- the old doc file names no longer appear (grep = 0, past CHANGELOG entries excepted);
- the string literals in `send`/`Embed`/`Modal` are identical before and after.

## Step 12 — `ruff format` + sorted imports

**Status:** done (2026-10-20). Line length 110 (the smallest reformatting diff among 88/100/110/120, and the
width the code was already written to); Markdown excluded from the formatter, since ruff 0.16 would also
reformat the hand-aligned Python examples in `docs/`. 43 import blocks sorted, 52 files reformatted in
`24cff10`, with an identical AST in all 67 Python files. `ruff` pinned to 0.16.6 in `requirements-dev.txt`
ahead of step 14, so a ruff release can't flip the CI format check.

**Changes:** `ruff.toml` adds `I` (isort) to `select` and a `[format]` section. A single reformatting commit,
with no other change. Its hash goes into `.git-blame-ignore-revs`. CI adds `ruff format --check .` to the
`lint` job.

**Validation:** `python -m ruff format --check .` and `python -m ruff check .` clean; the pytest suite stays
green (reformatting doesn't change behavior).

## Step 13 — `pre-commit` hooks

**Status:** done (2026-10-20). `pre-commit` 4.6.2 (4.7.0 was only 8 days old), `ruff-pre-commit` v0.16.6,
`pre-commit-hooks` v6.0.0, `conventional-pre-commit` v4.4.0 with the CLAUDE.md types and scopes, scope
optional, no `--strict` (it would reject merge commits). The first run fixed whitespace only: a trailing
space after the last card in `cards.txt` (already stripped on import) and missing final newlines.
Verified: a message without a type and one with an unknown scope (`feat(torneo): ...`) are refused, no commit
created; a message with scope and attribution trailer and one without scope pass. The CI lint job now runs
`pre-commit run --all-files` instead of the two ruff commands.

**Changes:**
- `.pre-commit-config.yaml` with these hooks, each with a pinned version (`rev`):
  - `ruff-pre-commit` (`ruff-check --fix`, `ruff-format`)
  - `conventional-pre-commit` (`commit-msg` stage), configured with the scopes in `CLAUDE.md`
  - base hooks: `check-yaml`, `end-of-file-fixer`, `trailing-whitespace`, `check-added-large-files`,
    `detect-private-key`
- `pre-commit` goes into `requirements-dev.txt`.
- CI runs `pre-commit run --all-files`.
- The local activation (`pre-commit install --hook-type pre-commit --hook-type commit-msg`) is documented in
  `README.md` and `CLAUDE.md`.

**Validation:** a commit with a non-conforming message is refused; `pre-commit run --all-files` is green.

## Step 14 — Reproducible dependencies

**Status:** done (2026-10-21). The six direct dependencies pinned to the production versions (`pip freeze`
of the bot's venv on the VM); transitive ones left to the direct pins' requirements — a full lockfile would be
stricter but needs regenerating on every upgrade. `pytest` pinned to the local version; `.python-version`
says 3.12. Verified: a clean Python 3.12.3 venv installs `requirements-dev.txt` and passes the whole suite.
Not verified: `docker build` (Docker Desktop wasn't running).

**Problem:**
- `requirements.txt` pins no versions, so a `pip install` on the production VM can bring in a new major of
  discord.py or SQLAlchemy.
- Python 3.14 runs locally, while CI and Docker use 3.12.

**Changes:**
- Pin in `requirements.txt` (with `==`) the versions installed in production today. They must be read with
  `pip freeze` on the VM, not from the local ones.
- Pin the rest of `requirements-dev.txt` too (`ruff` is pinned since step 12, `pre-commit` since step 13).
- Document Python 3.12 as the target (`.python-version`) in `README.md` / `docs/infrastructure.md`.

**Validation:** with a clean 3.12 venv, `pip install -r requirements-dev.txt` + pytest are green; `docker build`
succeeds.

## Step 15 — Measured coverage

**Status:** done (2026-10-21). `pytest-cov` 7.1.0 pinned; CI prints the report, no threshold yet. Baseline
(local run, Python 3.14, 231 tests): `database` 91.0%, `repositories` 86.7%, `services` 86.3%, `utils`
63.4% — **logic layers 73.2%** — `cogs` 13.2% (exempt from test-first), **total 49%**. `utils` is pulled
down by the two image generators (`deck_image_generator.py` 18%, `event_calendar_image_generator.py` 69%)
and `permissions.py` (0%). Next: set `--cov-fail-under` on the logic layers once the CI number is confirmed.

**Changes:** `pytest-cov` in `requirements-dev.txt`. In CI: `pytest --cov=services --cov=utils
--cov=repositories --cov=database --cov=cogs --cov-report=term-missing`, as a report only, no threshold. The
threshold (`--cov-fail-under`) comes later, set to the measured value, and from then on it can only go up.

**Validation:** the report shows up in the CI log. Record the baseline in this step.

## Step 16 — Wider lint: `B`, `ASYNC`, `UP`

**Status:** done (2026-10-20). Part 1: `B` and `ASYNC` enabled. On inspection the 5 `ASYNC`
findings all run once at startup (`setup_hook` cog loading, `init_db()`, the banlist import, the legacy card
cache check), before the bot serves any interaction — no real stall, contrary to the problem stated below. They
got a `# noqa` naming the rule and the reason rather than an `asyncio.to_thread` wrapper; the rules stay on to
catch runtime cases. `B007` fixed (unused loop variable). Part 2: `UP` enabled, 13 autofixes plus
`StrEnum` for the two enums (stored by name, verified with raw SQL: no data migration) and PEP 695 generics for
`BaseRepository`.

**Problem:** `ASYNC230`/`ASYNC240` flag blocking file I/O inside async functions (the event loop stalls during
the read/write, on a 1-OCPU VM); `B007` flags an unused loop variable.

**Changes:**
- Fix the 6 `B`/`ASYNC` findings (`asyncio.to_thread` or reading outside the async path), test-first where the
  behavior is observable.
- Add `B` and `ASYNC` to `select`.
- `UP` in a separate commit (automatic fixes).

**Validation:** `python -m ruff check .` clean with the new rules; pytest green.

## Step 17 — `ServiceResult` instead of matching on messages

**Status:** todo

**Problem:** 9 places in `cogs/tournament_system/cog.py` decide what to do by looking for phrases in the
service's message (`"non trovato" in msg`, `"completato" in msg`...). Rewording a message silently breaks the
cog's logic, with no test noticing.

**Changes:** the affected `TournamentService` methods return a `ServiceResult` (possibly with an enumerated
`reason` field); the cog decides on the result's fields. Test-first: the `test_tournament_service.py` tests
check `ok`/`reason`, not the text.

**Validation:** no `in msg` left in the cog (`grep`); pytest green; manual check in `TEST_MODE` of the commands
touched, recorded in `CHANGELOG.md`.

## Step 18 — English slash command names

**Status:** todo, no priority, to be decided in a dedicated session

**Problem:** command names are mixed (`/iscriviti`, `/classifica`, but `/forced_rarity_refresh`). A renamed
slash command leaves no alias: it must be announced to the community. Still to decide: which commands to rename,
and whether descriptions stay in Italian.

## Step 19 — Atomic write for the SPG override JSON

**Status:** done (2026-10-20, 3.6.6). Reused `save_json_state()` from `utils/sitemap_monitor.py`. Regression
test `TestOverrideFileSurvivesFailedWrite` (through `update_spg_overrides()`, with `json.dump` writing half
the file then raising) was red on the old code — the file on disk was left as `{"overrides": {` — and is
green now. `data/*.tmp` added to `.gitignore`, since an interrupted write leaves the `.tmp` behind next to a
tracked file (the monitors' `.tmp` files weren't ignored either).

**Problem:** `_save_override_data()` in `utils/arena_overrides.py` writes `data/arena_rarity_data.json` directly
with `open(..., "w")`. A crash mid-write leaves a truncated JSON, and on the next start `json.load` fails. The
file is tracked in git, so it can be restored, but the bot doesn't recover on its own. The old `CLAUDE.md`
claimed this write was atomic.

**Changes:** reuse `save_json_state()` from `utils/sitemap_monitor.py` (`.tmp` + `os.replace`), or move it to a
neutral module if importing it from the sitemap monitor reads oddly. Test-first: a failure during the write
leaves the previous file intact.

**Validation:** pytest green, including the new test.

## Step 20 — `.env.example` DB name typo

**Status:** done (2026-10-21). Fixed the template only: the bot reads the production `.env`, which wasn't
touched. If that `.env` was copied from the old template, it points at `data/clepsydra.db` and must stay that
way — renaming the variable there would open a new, empty DB. The production venv path was corrected in
`docs/infrastructure.md` at the same time (`venv/`, not `.venv/`, confirmed on the VM).

**Problem:** `.env.example` has `DB_PATH=data/clepsydra.db` (missing "h"), while the code default is
`data/clepshydra.db`. Copying the template as is gives a differently named DB file.

**Changes:** fix the value in `.env.example` and drop the note in `docs/infrastructure.md`. Check the production
`.env` before touching anything there: if it already uses the misspelled name, renaming it would point the bot
at a new, empty DB.

## Recommended Order (phase 2)

10 → 11 → 12 → 13 → 14 → 15 → 16 → 17 → 19 → 20; 18 when decided. Mechanical cleanup first (10), then the
translation (11), so the following diffs are already in English and free of line-ending noise. `ruff format`
(12) comes after the translation, because translating comments changes line lengths; then the gate (13) starts
from already compliant code. Reproducibility (14) and measurement (15) follow. Code fixes (16, 17, 19) come
last, when the gate and coverage are already active; 20 is a one-line fix that only needs a check of the
production `.env`.
