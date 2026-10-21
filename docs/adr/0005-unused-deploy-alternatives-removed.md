# ADR-0005 — Unused deploy alternatives removed: Docker and the systemd unit

**Status:** accepted (2026-10-21).

## Context

Production runs under `pm2` on the Oracle VM (`~/ClepshydraBot`, venv in `venv/`). Two other ways to run
the bot sat in the repository, both documented as alternatives and neither ever used in production:

- **Docker**: a `Dockerfile` (multi-stage, non-root user), a `docker-compose.yml` (named volume on
  `/app/data`, `env_file: .env`) and a `.dockerignore`, added in September 2026 (commit `36a7cd8`) to make
  the deploy reproducible. The only build ever checked was the one in September, on Docker Desktop. CI never
  built the image, and dependencies, layout and data files have changed since. The setup still shaped
  decisions: in 4.0.2 the seeds had to live outside `data/`, because `data/` was excluded from the image and
  mounted as a volume.
- **`deploy/clepshydrabot.service`**: a systemd unit that would start the bot at boot and restart it on
  failure. It was never installed on the VM, and it couldn't have worked: it pointed at
  `/opt/clepsydrabot/` (misspelled) with a `.venv/`, not at the real path and venv.

Checking the second one showed what was really missing. pm2 had no boot service on the VM (`pm2 startup` had
never been run), so a reboot would have left the bot down until someone started it by hand. The VM had been
up since 2026-08-09, so it never happened.

The project restructure (`docs/roadmap.md`, phase 2) moves most modules, which would give untested deploy
files one more way to break silently.

## Decision

- Delete `Dockerfile`, `docker-compose.yml`, `.dockerignore` and `deploy/`, with their sections in
  `README.md` and `docs/infrastructure.md`.
- `pm2` is the only deployment method. Its boot start is pm2's own systemd service: `pm2 startup systemd`
  was run on the VM on 2026-10-21, creating `pm2-ubuntu.service`, which runs `pm2 resurrect` at boot. `pm2
  save` stores the process list it restores. Steps: `docs/infrastructure.md` ("Deployment", "Updating
  production").
- `seeds/` stays at the root. The Docker reason is gone, but the folder still keeps tracked starting data
  apart from `data/`, which holds only runtime state ignored by git.

## Rejected alternatives

- **Keeping Docker and building the image in CI**: it proves the image builds, not that the bot runs in it,
  and it keeps a second deploy path to maintain for a single production environment that doesn't use it.
- **Fixing the systemd unit and switching to it**: it would replace a pm2 setup that works, logs where the
  docs and habits expect (`pm2 logs`), and now starts at boot too.
- **Keeping both as they are**: a deploy option nobody runs or tests looks like a fallback but isn't one, and
  the systemd unit was already wrong.

## Consequences

- One deploy path to document and verify. Moving to containers or to a plain systemd unit later means writing
  the setup against the code as it is then. The removed files are in git history (`git show 36a7cd8` for
  Docker, `git show b6e6eac^:deploy/clepshydrabot.service` for the unit) as a starting point.
- Whenever the pm2 process changes (name, interpreter, path), `pm2 save` must run again, or the boot restores
  the old list.
- The boot start is configured on the VM, not in the repository: a new VM needs `pm2 startup systemd` and
  `pm2 save` again.
