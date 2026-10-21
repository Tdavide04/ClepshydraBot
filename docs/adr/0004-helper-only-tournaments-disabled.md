# ADR-0004 — The bot is a helper only: tournament commands disabled

**Status:** accepted (2026-10-21, 4.0.0).

## Context

The community now hosts its tournaments on another platform. The bot's Swiss tournament system (registration,
deck submission, pairing, results, standings, Glicko-2 rating, `/leaderboard`) is no longer used, and keeping its
15 commands live means maintaining and verifying a feature nobody needs. What the bot still does for the
community: onboarding, Artisan deck checks and the banlist, the Wizards monitors.

## Decision

- `main.py` doesn't load `cogs/tournament_system` (`DISABLED_COGS`). Its slash commands, `/leaderboard`
  included, disappear from Discord at the next `tree.sync()`.
- `/banlist`, `/banlist_aggiungi` and `/banlist_rimuovi`, which lived in the tournament cog, moved to the deck
  validation cog and stay active.
- The tournament code stays in the repo, linted and tested: services, repositories, the cog, the DB tables and
  their data. Re-enabling it means removing one entry from `DISABLED_COGS`.

## Rejected alternatives

- **Deleting the tournament code**: smaller codebase, but bringing the feature back would take a revert, and the
  `tournaments`/`matches` tables and the rating history would be left without code that reads them.
- **Commenting the commands out**: dead code that neither ruff nor the tests check anymore, and that would rot.

## Consequences

- The tournament tests keep running, so the code doesn't rot while unused; roadmap work on it has no priority.
- `TOURNAMENT_CHANNEL_ID` is read but unused while the cog is disabled.
- The rating stops updating: the existing values stay in `users` untouched.
- Re-enabling: remove `"cogs.tournament_system"` from `DISABLED_COGS` (full module path since the explicit
  `EXTENSIONS` list), recompute the `docs/commands.md` lines, check
  the commands by hand in `TEST_MODE` (never done for the 3.6.7 `ServiceResult` refactor).
