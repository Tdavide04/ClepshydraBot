# Infrastructure

## Overview

ClepshydraBot is hosted on **Oracle Cloud Infrastructure (OCI) Free Tier**, running on a
`VM.Standard.E2.1.Micro` VM with 1 GB RAM.

---

## VM Specifications

| Parameter | Value |
|---|---|
| Provider | OCI Free Tier |
| Shape | VM.Standard.E2.1.Micro |
| Region | eu-milan-1 (Milan) |
| OCPU | 1 (AMD x86, not resizable) |
| RAM | 1 GB |
| Network | 0.5 Gbps |
| Storage | Block Storage |
| OS | Ubuntu 24.04 LTS |
| Public IP | 80.225.91.142 |

### Constraints

1 GB RAM drove key architectural choices:
- **SQLite** instead of PostgreSQL (no separate DB process)
- **SQLite tables and local JSON files** for caches instead of Redis (no external in-memory service)
- **Atomic file writes** (`.tmp` + `os.replace`) for the monitors' state files instead of a heavier journal

---

## Environment Configuration (`config/config.py`)

### Environment Variables

Loaded from `.env` via `python-dotenv` (template: `.env.example`):

| Variable | Description | Test Mode |
|---|---|---|
| `DISCORD_TOKEN` | Production bot token | `DISCORD_TOKEN_TEST` |
| `GUILD_ID` | Discord server | `GUILD_ID_TEST` |
| `PRESENTATION_CHANNEL_ID` | Presentation channel | `*_TEST` |
| `TOURNAMENT_CHANNEL_ID` | Tournament channel (optional, `0` = any channel) | `*_TEST` |
| `PUBLIC_DECK_CHANNEL_ID` | Public deck channel | `*_TEST` |
| `COMUNICATION_CHANNEL_ID` | Public community channel for monitor notifications (optional, `0` = off; note the spelling) | `*_TEST` |
| `LOG_CHANNEL_ID` | Staff log channel | none: shared by both modes |
| `INITIAL_ROLE` | Role given on join (e.g. `Viandante`), no default in code | same |
| `FINAL_ROLE` | Verified role (e.g. `Planeswalker`), no default in code | same |
| `ADMIN_ROLE` | Admin role (default: `Staff`) | same |
| `DB_PATH` | DB path (default: `data/clepshydra.db`) | `_test.db` suffix |
| `TEST_MODE` | Test flag | — |

`.env.example` still has `DB_PATH=data/clepsydra.db` (missing "h"): copying it as is gives a DB file name
different from the code default.

`VERSION` is **not** an environment variable: it is a hardcoded constant in `config/config.py` (`-test` is
appended when `TEST_MODE` is on), bumped by hand on every release together with `CHANGELOG.md` — see
"Versioning" at the top of that file for the convention (MINOR for features, PATCH for fixes).

### Test Mode

`TEST_MODE` switches:
- Discord token (production vs test)
- Discord server (guild ID)
- Destination channels (except the log channel)
- Database (`clepshydra.db` → `clepshydra_test.db`)

---

## Deployment

### Running with pm2 (current)

```bash
source .venv/bin/activate
pm2 start main.py --name ClepshydraBotte --interpreter .venv/bin/python
```

The production process is called **`ClepshydraBotte`** (case-sensitive — the log files are
`~/.pm2/logs/ClepshydraBotte-out.log`/`-error.log`). The docs said `clepshydrabot` until 3.5.3:
`pm2 logs clepshydrabot` finds no process, and a downstream `grep` returns empty output with no error,
easy to mistake for "no logs".

`pm2` manages the process and restarts it automatically on crash. Useful commands:

```bash
pm2 status              # process status
pm2 logs ClepshydraBotte  # live logs
pm2 restart ClepshydraBotte
pm2 save                # persists the process list
pm2 startup             # restarts pm2 (and the saved processes) when the VM boots

# history of the sitemap monitor checks (timestamped lines since 3.5.3)
pm2 logs ClepshydraBotte --lines 2000 --nostream | grep -E "BAN ANNOUNCEMENT|EVENT SCHEDULE"
```

`main.py` catches `discord.LoginFailure` and other startup exceptions, exits with a non-zero code and prints
an explicit error to stderr — visible in `pm2 logs ClepshydraBotte`. Note: if the token is genuinely
expired/invalid, `pm2` restarts the process anyway, and it fails again the same way until the token is
updated by hand — automatic restart doesn't "fix" a credentials problem, it only keeps it visible in the
logs.

### Running with systemd (unused alternative)

The unit file is in `deploy/clepshydrabot.service` (to copy into `/etc/systemd/system/`), kept in the
repository as an alternative but not installed on the production VM (which uses `pm2`):

```
[Unit]
Description=ClepshydraBot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/clepsydrabot
EnvironmentFile=/opt/clepsydrabot/.env
ExecStart=/opt/clepsydrabot/.venv/bin/python main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

With systemd, the same `main.py` behavior (non-zero exit on startup errors) would show up in
`journalctl -u clepshydrabot` instead of `pm2 logs`.

---

## Dependencies (`requirements.txt`)

```
discord.py
python-dotenv
aiohttp
Pillow
sqlalchemy[asyncio]
aiosqlite
```

Versions are not pinned yet (roadmap step 14), except `ruff` in `requirements-dev.txt`, which the CI
format check depends on.

Installation (production):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Installation (development, adds `pytest` and `ruff`):

```bash
pip install -r requirements-dev.txt
```

`pytest.ini` (`pythonpath = .`) explicitly adds the repo root to `sys.path`: without it, the bare
`pytest tests/` invocation (used by CI, unlike `python -m pytest`, which adds the cwd automatically) fails
with `ModuleNotFoundError` on the top-level modules (`services`, `database`, `utils`), because there is no
chain of `tests/__init__.py` up to the root.

---

## Logging

### Log System (`cogs/logger.py`)

Events are logged to a dedicated Discord channel as embeds:

| Level | Color | Events |
|---|---|---|
| `INFO` | Green | Completed operations (presentations, successful checks, tournament created) |
| `WARN` | Yellow | Failed validations, banned cards, invalid fields |
| `ERROR` | Red | Unhandled exceptions, Scryfall errors, DB problems |
| `DEBUG` | Blue | Startup, migrations, command sync |

Other cogs get the Logger with `bot.get_cog('Logger')` and call `send_log(level, event, info, ...)`.
Optional arguments:

- `fields`: list of `{"name", "value", "inline"}`, each added to the embed as a separate field.
- `files`: list of `discord.File`, attached to the same message.
- `extra_channel_id`: republishes the update to a second channel, normally
  `config.COMUNICATION_CHANNEL_ID`. It does nothing when it is `0`/`None`. The second channel gets a
  **separate** embed, built from `community_title`/`community_info`, not a copy of the log-channel one: the
  log embed carries staff details (who forced the check, "Forced manual check"/"Automatic check") that must
  not show up in the public channel, where `@everyone` gets pinged. The `files` are resent as they are:
  `discord.File.reset()` is called on each one first, because the first `send()` already consumed the
  stream.

`fields` and `files` are used by the Event Schedule and Banned and Restricted monitors (`docs/caching.md`).

Log-channel text is in English; the community embed is in Italian (`docs/adr/0003-project-language.md`).

### Console Logs

Besides the Discord channel, the bot writes logs to stdout/stderr for debugging over SSH; lines written with
`log()` (`utils/console.py`) carry a `[YYYY-MM-DD HH:MM:SS]` timestamp. Startup failures (invalid token,
unhandled exceptions in `setup_hook`) are always written to stderr with the `FATAL:` prefix, even when the
Discord log channel is unreachable.

---

## Infrastructure Roadmap

### Sprint 7 — Docker (done)

Multi-stage `Dockerfile`: a `builder` stage installs the dependencies into an isolated venv (`/opt/venv`), the
final stage copies only the prebuilt venv + the application code and runs as a non-root user (`clepshydra`,
uid 1000). `.dockerignore` excludes `.git`, `data/` (never baked into the image — it only holds runtime/cache
data, recreated from the volume on every start), `.env` (never in the image, injected at runtime), tests/docs.

`docker-compose.yml`:
- `restart: unless-stopped`
- `env_file: .env` (read from the host at startup, not copied into the image)
- named Docker volume `clepshydra-data` mounted on `/app/data` — persists across container restarts

```bash
docker compose up -d --build   # build + start
docker compose logs -f bot     # live logs
docker compose down            # stop (the data volume stays)
```

This is an **additional** deployment option, it doesn't replace `pm2` ("Deployment" section above), which
stays the method actually used in production until a migration is decided.

### Sprint 8 — CI/CD (done)

`.github/workflows/ci.yml`, active on push/PR:
- `pytest` on every push and PR — **blocking gate**
- `ruff` lint (`ruff.toml`, rules `E4,E7,E9,F,I`) — **blocking gate**: the pre-existing lint debt
  (~54 issues) was cleared in Step 8 of `docs/roadmap.md` (at the time partly by excluding `legacy/`, later
  removed from the repository — see `CHANGELOG.md`)
- `ruff format --check .` (line length 110, Markdown excluded) — **blocking gate** since roadmap step 12;
  the lint job installs the `ruff` version pinned in `requirements-dev.txt`. The one-off reformatting commit
  is listed in `.git-blame-ignore-revs`

Still to do:
- Docker `build` check in CI (verify the image builds on every push, without deploying)
- Automatic deployment to OCI via SSH/deploy key
