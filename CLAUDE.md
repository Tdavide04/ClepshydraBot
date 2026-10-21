# CLAUDE.md

ClepshydraBot is a Discord helper bot (discord.py) for the "Clepshydra" MTG Arena community. It covers:

- member onboarding
- Artisan-format deck validation against Scryfall
- monitors for Wizards' Arena Event Schedule and Banned and Restricted pages

The Swiss tournament system (`cogs/tournament_system/`, `services/`) is **disabled** since 4.0.0: the cog is
in `DISABLED_COGS` in `main.py`, so its commands aren't registered, but its code, tests and DB tables stay
(`docs/adr/0004-helper-only-tournaments-disabled.md`). Don't add tournament features unless it's re-enabled.

**Language** (`docs/adr/0003-project-language.md`):
- **English** for everything developers and logs see: code, comments, docstrings, test names, console
  output, Discord log channel, docs, commits, new CHANGELOG entries.
- **Italian** for everything a user sees as a reply to an action or in a public channel: command
  replies (admin ones included), modals, views, service messages, community embeds, slash command names
  and descriptions. These strings stay inline in the code.
- A few Italian identifiers remain from before the rule (`User.nome`, `torneo_name`, `titolo`...); slash
  command parameters such as `carta` and `giocatore` are UI and stay Italian.

## Working standard

Decided in `docs/adr/0002-development-standard.md`. Every change follows this loop.

1. **Orient.** Read the topic doc for the area (see the map below) and any `docs/adr/` entry that touches
   it. Use the terms defined in `CONTEXT.md`. Check `git log` on `main` and on open `feature/*` branches,
   since parallel work may already have touched the area. Done when you can name the files you will change
   and the behaviour you will change.
2. **Red.** Write the test first for logic in `features/`, `services/`, `utils/`, `core/`, `repositories/`
   or `database/`. A bug fix starts from a regression test that fails on the current code, and fails on an
   assertion about behaviour rather than on an import error. Use the `tdd` skill. Done when the new test is red for the
   reason you expect.
3. **Green.** Write the smallest change that turns the test green. Done when `python -m pytest` is fully
   green.
4. **Refactor.** Remove duplication and sharpen names while the suite stays green. Keep the scope to the
   change at hand: unrelated debt goes into `docs/roadmap.md`, not into this diff.
5. **Gate.** Run `python -m pytest`, `python -m ruff check .` and `python -m ruff format --check .`.
   All must pass (CI runs the same three).
6. **Truthful docs.** Update every doc whose description the change made stale (`docs/`, `README.md`,
   this file). Then:
   - add a `CHANGELOG.md` entry in the existing format
   - bump `VERSION` in `config/config.py`, by hand, in the same commit (see the semver mapping below)

   Done when no doc describes the old behaviour.
7. **Commit**, only when the user asks or has approved a series. One approved point = one commit = one
   version.

**Cogs are exempt from step 2.** Cogs are the Discord UI layer, so keep them thin: a decision that can be
tested belongs in a service. Verify cog changes by hand under `TEST_MODE=True` and write what you checked
in the CHANGELOG entry.

### Pragmatic rules

- **DRY applies to knowledge, not just code.** Every fact has one owning doc, and this file points to it
  rather than repeating it. Code example: `features/monitors/sitemap.py`, extracted once two monitors had
  duplicated it.
- **No broken windows.** The lint set only grows. A rule family joins `ruff.toml` once the code is clean
  for it. Every `# noqa` names the rule and gives a reason.
- **Tracer bullets.** Build a new feature as a thin end-to-end slice first: command → service →
  repository → test. Then widen it.
- **Programming by coincidence is banned.** Verify external behaviour (Scryfall queries, Wizards HTML,
  Discord limits) live before relying on it, and record the evidence in the topic doc.
- **Explicit contracts.** Services return `ServiceResult(ok, message, kind=None)` (`core/results.py`),
  and cogs branch on its fields, never on the message text. Add a `ResultKind` member only when `ok` alone
  can't tell the caller's cases apart.
- **Fail loud.** On unexpected input, return `None`, raise, or log a `WARN` that asks for a manual check,
  as the monitor parsers do. Never post a guessed result as if it were authoritative.

### Conventional Commits

Format: `<type>(<scope>): <subject>`.

- **Subject:** English, lowercase, imperative, no trailing period, at most about 72 chars. It describes
  the outcome for users or staff (`fix(tournament): ignore unplayed matches in mid-round standings`).
- **Body:** why the change was made, and what was verified.
- **Footer:** `Refs: #<issue>`, `BREAKING CHANGE: ...` when it applies, plus the attribution trailer.
- **Scopes** (optional, one per commit): `tournament`, `deck`, `banlist`, `cache`, `monitor`,
  `onboarding`, `logger`, `db`, `deps`, `ci`, `lang`. The `commit-msg` hook in `.pre-commit-config.yaml`
  enforces this list: add a scope in both places.

Type → `VERSION` bump (MAJOR moves only when the user decides it explicitly):

| Type | Bump |
|---|---|
| `feat` | MINOR |
| `fix`, `perf` | PATCH |
| `refactor`, `docs`, `test` released as their own point | PATCH (as in 3.6.3) |
| `!` / `BREAKING CHANGE` | MAJOR |
| `style`, `chore`, `ci`, `build` that leave the running bot unchanged | none |

**A mechanical change across several areas is one point** (for example the translation): several
commits, one per area, but a single CHANGELOG entry and a single bump, in the last commit.

`pre-commit` enforces all of this: on commit it runs ruff check, ruff format and whitespace/YAML/private-key
checks, and rejects a message that isn't Conventional Commits with a listed type and scope. Activate it once
per clone (see Commands). CI runs the same pre-commit-stage hooks on every file.

### Branches and versions

- Work on a `feature/<topic>` branch cut from `main` (for example `feature/event-calendar`). `main` only
  receives merges via PR, and the branch is deleted after the merge.
- `VERSION` is a hardcoded constant in `config/config.py`, shown in the `SYSTEM_STARTUP` log.

### Agent tooling

- **Skills:**
  - `tdd` for every logic change
  - `diagnosing-bugs` when something is broken or slow
  - `code-review` before a PR to `main`
  - `grilling` to stress-test a plan
  - `domain-modeling` to add a term to `CONTEXT.md` or write an ADR when one is settled (this repo names
    the glossary `CONTEXT.md`, not `GLOSSARY.md`)
- **Recommended plugins** (installed per machine, `@claude-plugins-official`):
  - `pyright-lsp`: type diagnostics and references
  - `pr-review-toolkit`: test, error-handling and type-design review
  - `security-guidance`: secrets and injection checks on edits. The repo is public and handles a
    Discord token.
  - `claude-md-management`: audit of this file

## Commands

```bash
pip install -r requirements-dev.txt          # deps + pytest + ruff + pre-commit
pre-commit install --hook-type pre-commit --hook-type commit-msg   # once per clone
python main.py                                # needs .env (see .env.example)
TEST_MODE=True python main.py                 # _TEST-suffixed token/guild/channels/db
python -m pytest                              # CI runs `pytest tests/ -v` plus a coverage report
python -m pytest --cov=core --cov=services --cov=utils --cov=repositories --cov=database --cov-report=term-missing
python -m pytest tests/tournament/test_pairing_engine.py::TestCalculateRounds -v
python -m ruff check .                        # blocking CI gate
python -m ruff format .                       # CI runs `ruff format --check .`
pre-commit run --all-files                    # what the CI lint job runs
```

Target Python is 3.12 (CI, `ruff.toml`, production venv).

## Architecture map

Layering: **Cogs → Services → Repositories → Database**, plus cross-cutting `core/` (logging, error
handling, `ServiceResult`, JSON state, permissions). A finished feature lives in its own `features/<name>/`
package (cog, logic, data access together); `utils/` holds feature code still waiting to move
(`docs/roadmap.md` phase 2). Each layer calls only
the layer below it, and repositories hold no business logic. Overview: `docs/architecture.md`.

| Area | Code | Topic doc |
|---|---|---|
| Swiss tournaments (disabled) | `cogs/tournament_system/`, `services/` | `docs/tournaments.md` |
| Artisan deck validation | `cogs/deck_validation/` | `docs/deck-validation.md` |
| Banlist | `repositories/banlist_repository.py`, `validators.py` | `docs/banlist-system.md` |
| Scryfall card cache, SPG overrides | `utils/card_cache.py`, `utils/arena_overrides.py` | `docs/caching.md` |
| Wizards monitors (Event Schedule, Banned and Restricted, calendar image) | `features/monitors/` | `docs/caching.md` |
| Onboarding | `cogs/presentation/` | `docs/onboarding.md` |
| Schema and migrations | `database/` | `docs/database.md` |
| Config, logging, deploy | `config/config.py`, `core/logger.py`, `main.py` | `docs/infrastructure.md` |
| Slash command list | `cogs/` | `docs/commands.md` |
| Roadmap (project structure refactor) | | `docs/roadmap.md` |
| Decisions and rationale | | `docs/adr/` |

`cogs/deck_validation/` was named `cogs/tournament/` before 1.3.1, and older CHANGELOG entries still use
that name.

### Invariants

Breaking one of these has already caused a production bug. Each one is explained in the topic doc
listed in the map.

- **A new extension goes into `EXTENSIONS` in `main.py`.** Nothing discovers cogs from the folder; the
  `tests/core/test_extensions.py` check fails until the module is listed.
- **Every modal and view subclasses `ReportingModal` or `ReportingView`** (`core/interaction_errors.py`).
  Slash commands are covered by `bot.tree.on_error` (`core/error_handler.py`); modals and views are not.
- **A Scryfall failure is not an "illegal card" verdict.** Any non-200 response after retries raises
  `ScryfallUnavailable`, and `validate_deck()` then sets `service_error` and marks no card. A 404 on
  `/cards/search` is a real answer ("no Arena prints"). Keep the two cases separate.
- **The background tasks in `main.py:setup_hook` start after `tree.sync()` and the startup logs.** The
  comment there explains why.
- **One slash-command description over 100 chars breaks `tree.sync()` for the whole batch**, and the bot
  crashes on every restart.
- **Schema changes go through `_SCHEMA_MIGRATIONS` in `database/engine.py`** as a `(table, column, ddl)`
  tuple. There is no Alembic.
- **The banlist cache is module-level and shared by both `ArtisanService` instances.** Invalidate it with
  `reload_banlist()` and never reload a single instance.
- **The Wizards monitors are notification-only.** They never write to `banned_cards`. They select pages
  by the newest sitemap `lastmod`, and a parser that cannot find the expected structure returns `None`,
  which logs a `WARN`.
- **Anything posted to `COMUNICATION_CHANNEL_ID` is a dedicated community embed** with no staff detail.
  Note the spelling of the constant. `LOG_CHANNEL_ID` has no `_TEST` variant.
- **Inside `utils/`, `core/` and `features/monitors/` (except the `core/logger.py` extension),
  `config.config` is imported inside the function that uses it**, never at module top, so these modules stay
  importable in tests without a `.env`. Examples: `core/permissions.py` and the two monitors.
- **Production runs under `pm2`** on an Oracle VM (1 OCPU / 1 GB), started at boot by the `pm2-ubuntu`
  systemd service from the list saved with `pm2 save`. pm2 is the only deployment method (ADR-0005).

### Writing tests

- **`pytest.ini` sets `pythonpath = .`**, so the bare `pytest tests/` command works the way CI runs it.
- **Each `tests/*/conftest.py` seeds its own env vars**, duplicated on purpose. The seeding must run
  before any application import in that file: `services/__init__.py`, `database.engine` and
  `cogs.deck_validation.service` all load `config.config` at import time.
- **There is no `pytest-asyncio`.** Each async scenario runs inside one `asyncio.run()` against a temp
  SQLite DB, because aiosqlite binds connections to the loop that created them.
- **Mock only at the network edge**, for example by replacing `_post_with_retry`/`_get_with_retry` on the
  `ArtisanService` instance. Keep the DB real.
- **`tests/deck_validation/conftest.py` provides `isolated_db`, `isolated_card_cache` and
  `isolated_banlist_cache`.** They reset `utils.card_cache`'s module globals (`_card_cache`, `_loaded`,
  `_dirty_upserts`, `_dirty_deletes`). Use them in any test that touches the card cache.

## Docs conventions

- Refer to code by symbol name (`check_banlist()` in `validators.py`), not `file.py:line`. The one
  exception is the "Line" column of `docs/commands.md`: recompute it whenever `cogs/` files shift.
- Leave volatile counts (tests, commands) out of docs: they go stale with every change.
- Write rationale and rejected alternatives as an ADR (`docs/adr/NNNN-title.md`), not in this file.

## Agent skills

- **Issue tracker:** GitHub Issues for `Tdavide04/ClepshydraBot`, through the `gh` CLI. See
  `docs/agents/issue-tracker.md`.
- **Triage labels:** `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See
  `docs/agents/triage-labels.md`.
- **Domain docs:** single-context layout, `CONTEXT.md` + `docs/adr/` at the repo root. See
  `docs/agents/domain.md`.
