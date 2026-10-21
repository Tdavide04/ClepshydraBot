# ADR-0002 — Development standard: test-first, Conventional Commits, automated gates

**Status:** accepted (2026-10-20). Automated gates in place since 3.6.6 (`ruff format` and `pre-commit`).

## Context

Discovery of 2026-10-20. The project already had good habits, but only by convention:

- 53 commits out of 63 follow `type: description`, with no scope and no check.
- Recent fixes have a regression test that fails on the previous code (e.g. 3.6.2), but there is no written
  rule.
- Lint covers only `E4,E7,E9,F`. `ruff format` has never been applied (57 files out of 84 to reformat).
- Dependencies have no pinned versions and there is no local hook.
- `cogs/tournament_system/cog.py` has 9 places that decide what to do by looking for phrases in the message the
  service returns.

## Decision

1. **Test-first for logic** (`services/`, `utils/`, `repositories/`, `database/`): red → green → refactor.
   Every bug fix starts from a regression test that fails on the current code. Cogs (Discord UI) are exempt:
   they stay thin, and the manual check in `TEST_MODE` is recorded in `CHANGELOG.md`.
2. **Conventional Commits** with project scopes and an English subject (ADR-0003); the type decides the
   version bump (see `CLAUDE.md` → "Conventional Commits").
3. **Automated gates**: the `pre-commit` framework (ruff check, ruff format, commit message check) and the same
   checks in CI. The lint set only grows: a new rule family joins `ruff.toml` only once the code is already
   clean for it.
4. **A lean `CLAUDE.md`**: it holds rules, commands, a map and invariants. Historical rationale goes into ADRs
   in `docs/adr/` or into the topic documents in `docs/`.

## Rejected alternatives

- **Husky / lint-staged** (the `setup-pre-commit` skill): Node ecosystem, unsuited to a Python project.
- **Test-first for cogs too**, with fakes of `discord.Interaction`: high upfront cost and brittle tests for the
  value they give. Moving decisions into services, which are testable, is preferred.
- **Written rules only, no enforcement**: conventions stay in the memory of whoever is working.

## Consequences

- A one-off reformatting commit is needed (done in 3.6.6), which pollutes `git blame`: it goes into
  `.git-blame-ignore-revs`.
- The "cog ↔ service string matching" debt becomes an explicit roadmap step (done in
  3.6.7) instead of staying a note.
