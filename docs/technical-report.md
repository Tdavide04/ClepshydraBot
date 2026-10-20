# ClepshydraBot — Technical Report

**Document version 2.0 — September 2026**
**Author: tdavide — Confidential**

Short reference sheet on where and how the bot runs in production. For architecture, features, commands,
caching and the operational roadmap, see [Related Documentation](#related-documentation) at the bottom:
this document doesn't repeat them.

---

## 1. Production Instance

| Field | Value |
|---|---|
| Provider | Oracle Cloud Infrastructure — Free Tier |
| Region | eu-milan-1 (AD-1, Fault Domain: FD-2) — Milan, Italy |
| Instance OCID | `ocid1.instance.oc1.eu-milan-1.anwgsljrtzu6yzqc...` |
| Launch date | May 4, 2026, 20:29:36 UTC |
| Public IP | 80.225.91.142 |
| SSH username | ubuntu |
| Access | SSH with a private key |
| Process manager | `pm2` — restarts the bot automatically on crash |

## 2. Hardware Specifications

| Spec | Value |
|---|---|
| Shape | VM.Standard.E2.1.Micro |
| OCPU | 1 (not resizable) |
| RAM | 1 GB |
| Network | 0.5 Gbps |
| Storage | Block Storage only (no local disk) |
| Encryption | In-transit encryption enabled |
| Firmware | UEFI_64 |
| Launch Mode | PARAVIRTUALIZED |

## 3. Operating System

| Spec | Value |
|---|---|
| OS | Canonical Ubuntu 24.04 LTS |
| Image | Canonical-Ubuntu-24.04-2026.03.31-0 |
| Secure Boot | Disabled |
| Measured Boot | Disabled |
| TPM | Disabled |
| IMDS | Version 2 only |

## 4. Technology Stack

### 4.1 Python Dependencies (`requirements.txt`, production)

| Library | Role |
|---|---|
| `discord.py` | Discord API integration: slash commands, modals, select menus, events, cogs |
| `aiohttp` | Async HTTP client for Scryfall and the Wizards sitemap (retry + rate limiting) |
| `Pillow (PIL)` | Deck showcase and event calendar images |
| `python-dotenv` | Loading `.env` |
| `SQLAlchemy[asyncio]` | Async ORM |
| `aiosqlite` | Async SQLite driver |

`requirements-dev.txt` adds `pytest` and `ruff` for development/CI.

### 4.2 External Services

| Service | Usage |
|---|---|
| Discord API | WebSocket gateway (events) + REST (messages, embeds, files) |
| Scryfall API | `POST /cards/collection` (batch fetch), `GET prints_search_uri` (Arena legality) |
| magic.wizards.com | `sitemap.xml` + Event Schedule and Banned and Restricted pages (monitors, see `docs/caching.md`) |

### 4.3 Versions

| Component | Version |
|---|---|
| Python | 3.12+ |
| discord.py | Latest stable (not pinned yet, see roadmap step 14) |
| Bot | see `CHANGELOG.md` for the current version |

## 5. Resource Constraint

With 1 OCPU and 1 GB RAM (not resizable on the Free Tier), the bot is designed to keep memory and CPU use
low. This constraint drove key architectural choices: SQLite instead of PostgreSQL, SQLite tables and local
JSON files for caches instead of Redis, a single process (no separate worker). The details of these choices
and their trade-offs are tracked in `docs/infrastructure.md` ("Constraints" section) and in the roadmap.

---

## Related Documentation

| Topic | Document |
|---|---|
| Deployment, environment variables, logging, dependencies, CI | `docs/infrastructure.md` |
| Layered architecture (cogs/services/repositories/database) | `docs/architecture.md` |
| Slash commands and permissions | `docs/commands.md` |
| Database schema and migrations | `docs/database.md` |
| Caching and external APIs (Scryfall, rarity overrides, Wizards monitors, banlist) | `docs/caching.md` |
| Artisan deck validation | `docs/deck-validation.md` |
| Banlist system | `docs/banlist-system.md` |
| Onboarding (presentations) | `docs/onboarding.md` |
| Swiss tournament system | `docs/tournaments.md` |
| Technical debt and improvement plan | `docs/roadmap.md` |
| Decisions and rationale | `docs/adr/` |
| Guide for Claude Code | `CLAUDE.md` |
