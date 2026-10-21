# Command Reference

Command and parameter names are the real slash-command names, in Italian, as users type them.

## Public Commands

### Onboarding

| Command | Description | Mode |
|---|---|---|
| `/presentati` | Starts the multi-step presentation wizard | Modal + Select + Preview |

### Deck Validation

| Command | Description | Mode |
|---|---|---|
| `/artisan_check_deck` | Checks an Artisan deck's legality | Modal (text decklist) |

### Tournaments (disabled since 4.0.0)

The commands in the tournament sections below are **not registered**: `cogs/tournament_system` is in
`DISABLED_COGS` (`docs/adr/0004-helper-only-tournaments-disabled.md`). They're kept here for when the cog is
re-enabled.

### Tournaments — Registration

| Command | Description |
|---|---|
| `/iscriviti [torneo_id]` | Registers for the tournament (no deck required here) |
| `/invia_deck [torneo_id]` | Submits/updates the deck for an existing registration — required before the start, repeatable |
| `/iscrizioni_torneo [torneo_id]` | Lists registrations with deck status (✅ submitted / ⏳ pending) |
| `/left_torneo [torneo_id]` | Unregisters before the start |

### Tournaments — Playing

| Command | Description |
|---|---|
| `/risultato [torneo]` | Submits a match result (game-wins select menu). The first of the two players to submit wins: a second submission is refused privately, with no public announcement — if the result is wrong, staff fixes it with `/correggi_risultato` |
| `/classifica [torneo_id]` | Shows the standings with points and OMW |
| `/turni [torneo_id]` | Pairings of the current round |

### Tournaments — Information

| Command | Description |
|---|---|
| `/lista_tornei` | Lists every tournament with ID, name, status, players |
| `/leaderboard [limite]` | Glicko-2 rating leaderboard (default: 10) |
| `/banlist` | List of banned cards in a paginated embed |

---

## Admin Commands (`Staff` role)

### Tournament Management

| Command | Description |
|---|---|
| `/crea_torneo` | Opens a modal to create a new tournament (name, format, max players) |
| `/avvia_torneo [torneo]` | Moves registration → active status, generates round 1 — refuses if an active registered player hasn't submitted a valid deck yet |
| `/torneo_next_turn [torneo]` | Generates the next round or completes the tournament |
| `/drop_giocatore <giocatore> [torneo]` | Forced removal: during registration it removes the registration (unblocks `/avvia_torneo` if the player never submitted a deck), on an active tournament with an auto-loss |
| `/concludi_torneo [torneo]` | Early conclusion with rating update |
| `/correggi_risultato <tavolo> <esito> [vincitore] [turno] [torneo]` | Overwrites (or enters, if missing) a match result of the running tournament: `esito` 2-0 / 2-1 / draw, `vincitore` required except for a draw, `turno` defaults to the current round. Past rounds too: standings recompute, pairings already generated stay. Refused once the tournament is concluded (ratings already computed). Public announcement + `RESULT_CORRECTED` log |

### Banlist Management

| Command | Description |
|---|---|
| `/banlist_aggiungi <carta>` | Adds a card to the banlist (invalidates the in-memory cache right away) |
| `/banlist_rimuovi <carta>` | Removes a card from the banlist (invalidates the in-memory cache right away) |

### Maintenance

| Command | Description |
|---|---|
| `/forced_rarity_refresh` | Forces an immediate SPG override check (it also runs on its own every week — see `docs/caching.md`) |
| `/forced_event_schedule_check` | Forces an immediate re-check of the latest Arena "Event Schedule" page, ignoring the last saved `lastmod` (it also runs on its own every 2 hours — see `docs/caching.md`); posts the calendar image to both the log channel and the community channel |
| `/forced_ban_announcement_check` | Forces an immediate re-check of the latest Banned and Restricted Announcement, ignoring the last saved `lastmod` (it also runs on its own every 2 hours — see `docs/caching.md`); if there are real changes, posts to both the log channel and the community channel (log channel only if that announcement was already notified to the community) — notify-only, never touches the Artisan banlist |
| `/invalidate_card_cache <carta>` | Removes a card from the Scryfall cache, forcing a full re-check on the next validation (without waiting for the 30-day TTL) |

---

## Implementation Details

### File Locations

The "Line" column points at each command's `async def`: recompute it whenever `cogs/` files shift.

| Command | File | Line |
|---|---|---|
| `/presentati` | `cogs/presentation/cog.py` | 47 |
| `/artisan_check_deck` | `cogs/deck_validation/__init__.py` | 59 |
| `/crea_torneo` | `cogs/tournament_system/cog.py` | 561 |
| `/avvia_torneo` | `cogs/tournament_system/cog.py` | 570 |
| `/torneo_next_turn` | `cogs/tournament_system/cog.py` | 833 |
| `/drop_giocatore` | `cogs/tournament_system/cog.py` | 665 |
| `/concludi_torneo` | `cogs/tournament_system/cog.py` | 791 |
| `/correggi_risultato` | `cogs/tournament_system/cog.py` | 725 |
| `/iscriviti` | `cogs/tournament_system/cog.py` | 990 |
| `/invia_deck` | `cogs/tournament_system/cog.py` | 1052 |
| `/iscrizioni_torneo` | `cogs/tournament_system/cog.py` | 1084 |
| `/left_torneo` | `cogs/tournament_system/cog.py` | 1128 |
| `/risultato` | `cogs/tournament_system/cog.py` | 1172 |
| `/classifica` | `cogs/tournament_system/cog.py` | 1246 |
| `/turni` | `cogs/tournament_system/cog.py` | 1336 |
| `/lista_tornei` | `cogs/tournament_system/cog.py` | 940 |
| `/leaderboard` | `cogs/tournament_system/cog.py` | 1345 |
| `/banlist` | `cogs/deck_validation/__init__.py` | 63 |
| `/banlist_aggiungi` | `cogs/deck_validation/__init__.py` | 103 |
| `/banlist_rimuovi` | `cogs/deck_validation/__init__.py` | 126 |
| `/forced_rarity_refresh` | `cogs/spg_override_updater.py` | 27 |
| `/forced_event_schedule_check` | `cogs/arena_event_schedule_updater.py` | 26 |
| `/forced_ban_announcement_check` | `cogs/ban_announcement_updater.py` | 26 |
| `/invalidate_card_cache` | `cogs/spg_override_updater.py` | 87 |

---

## Helpers and Utilities

### TournamentSystemCog — Helpers

| Helper | Description |
|---|---|
| `_resolve_tournament(torneo, torneo_id)` | Finds the tournament by name/ID (`torneo`), by ID (`torneo_id`), or falls back to the latest one |
| `_check_tournament_channel(interaction)` | Refuses the command outside `TOURNAMENT_CHANNEL_ID` (no-op when it is `0`) |
| `_resolve_name(tp)` / `_player_display(tp)` | Display name of a tournament player (server nickname, `Giocatore #id` fallback); `_player_display` adds the deck name |
| `_show_pairings(interaction, torneo_id)` | Shared body of `/turni` |
| `_log(level, event, user, info)` | Shortcut to `Logger.send_log()` |

### Permissions

`is_admin()` check (`utils/permissions.py`):
- Checks that the user has the `ADMIN_ROLE` role (default: `Staff`)
- Used as a decorator on admin commands: `@is_admin()`
