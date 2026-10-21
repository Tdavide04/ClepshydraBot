# ADR-0005 — The unused Docker setup is removed

**Status:** accepted (2026-10-21).

## Context

A `Dockerfile` (multi-stage, non-root user), a `docker-compose.yml` (named volume on `/app/data`,
`env_file: .env`) and a `.dockerignore` were added in September 2026 (commit `36a7cd8`) to make the deploy
reproducible. They were always documented as an extra option. Production kept running under `pm2` on the
Oracle VM, with the venv in `venv/`, and no migration was ever planned.

By October 2026:

- the only build ever checked was the one in September, on Docker Desktop. CI never built the image, and
  dependencies, layout and data files have changed since;
- the setup still shaped decisions: in 4.0.2 the seeds had to live outside `data/` because `data/` was
  excluded from the image and mounted as a volume;
- the project restructure (`docs/roadmap.md`, phase 2) moves most modules, which would give an untested
  image one more way to break silently.

## Decision

- Delete `Dockerfile`, `docker-compose.yml` and `.dockerignore`, and the Docker sections of `README.md` and
  `docs/infrastructure.md`.
- `pm2` on the VM is the only deployment method. Its steps are in `docs/infrastructure.md` ("Deployment",
  "Updating production").
- `seeds/` stays at the root. Without Docker the original reason is gone, but the folder still keeps tracked
  starting data apart from `data/`, which holds only runtime state ignored by git.

## Rejected alternatives

- **Keeping it and building the image in CI**: it proves the image builds, not that the bot runs in it, and
  it keeps a second deploy path to maintain for a single production environment that doesn't use it.
- **Keeping it as is**: a deploy option nobody runs or tests looks like a fallback but isn't one.

## Consequences

- One deploy path to document and verify. Moving to containers later means writing the setup against the
  code as it is then. The removed files are in git history (`git show 36a7cd8`) as a starting point.
- `deploy/clepshydrabot.service` (systemd) is the same kind of unused alternative. It stays for now: it
  constrains nothing, and removing it is a separate decision.
