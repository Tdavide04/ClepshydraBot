# ADR-0003 — Project language: English for developers, Italian for users

**Status:** accepted (2026-10-20). Translation of the existing material is roadmap step 11.

## Context

Until 3.6.4, code identifiers were in English and everything else was in Italian: comments, docstrings,
test names, console and log-channel messages, docs, CHANGELOG, commit subjects.

The repo is public, so it also serves as a portfolio. Agents work on it daily. When the code, the docs
and the prompts share one language, an agent does not have to translate between them, and terms are
less ambiguous.

The community the bot serves is Italian, and so are its members and staff.

## Decision

**English** covers everything developers and logs see:
- identifiers, comments, docstrings, test names
- console output (`pm2 logs`) and the Discord log channel (`Logger.send_log()` `info`/`fields`)
- `docs/` (file names included), `README.md`, `CLAUDE.md`, ADRs, `CONTEXT.md`
- commit subjects and scopes, and new `CHANGELOG.md` entries
- comments in supporting files (`.env.example`, `Dockerfile`, CI, `deploy/`, `ruff.toml`)

**Italian** covers everything a user sees as a reply to an action or in a public channel:
- replies to every slash command, admin ones included
- modals, views, and the messages services return to cogs
- community-channel embeds (`community_title`/`community_info`)
- slash command names and descriptions (renaming is roadmap step 18, to be decided separately)

**Unchanged:**
- git history
- past `CHANGELOG.md` entries (up to 3.6.4)
- data files (`cards.txt`, `data/*.json`)
- `COMUNICATION_CHANNEL_ID`: fixing the typo means renaming an env var, which is a separate fix

Italian UI strings stay inline in the code. They are not extracted into a catalog.

## Rejected alternatives

- **Everything in English, UI included:** members would have to relearn about 20 commands in a language
  that is not theirs.
- **i18n** (UI strings in a catalog, Italian by default): high cost with no current need. If the bot
  ever serves other communities, i18n becomes its own step.
- **Rewriting git history:** it would need a force push on a public repo and break the commit hashes
  cited in the docs.

## Consequences

- `CONTEXT.md` maps English code terms to the Italian UI terms (registration ↔ iscrizione,
  round ↔ turno, standings ↔ classifica, deck ↔ mazzo, ...), so agents don't invent synonyms.
- A test that asserts on log text must change together with that text. A test that asserts on a UI
  string must not change.
