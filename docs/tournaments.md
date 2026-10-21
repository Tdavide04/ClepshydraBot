# Swiss Tournament System

## Overview

The tournament system manages the whole lifecycle of a Swiss tournament for Magic: The Gathering Arena. It
supports registration, automatic pairing, result submission, standings with tiebreakers and Glicko-2 rating.

---

## Structure

```
services/
├── tournament_service.py   # Orchestrator: coordinates every operation
├── pairing_engine.py       # Swiss pairing algorithm
├── standings.py            # Standings with tiebreakers
├── rating.py               # Glicko-2 rating system
└── results.py              # ServiceResult(ok, message, kind) + ResultKind

cogs/tournament_system/
└── cog.py                  # 15 slash commands + modals + views

utils/
├── tournament_logic.py     # Utilities (OMW bar, rank label, columns)
└── tournament_embeds.py    # Embed builders (standings, pairings, start, top8)
```

---

## Tournament Lifecycle

```
CREATION (admin)
    │ /crea_torneo → name, format, max players
    ▼
REGISTRATION
    │ /iscriviti → direct registration, no deck required
    │ /invia_deck → InviaDeckModal (deck validation + submit), repeatable
    │ /iscrizioni_torneo → who is registered and who has already submitted a deck
    │ /left_torneo → voluntary leave
    │ /drop_giocatore (admin) → removes a registration (e.g. a player who never
    │                           submits a deck and would otherwise block the start)
    ▼
START (admin)
    │ /avvia_torneo → blocked if an active registered player hasn't
    │                 submitted a valid deck yet (lists who is missing)
    │               → otherwise: round count, round 1 pairings
    ▼
ACTIVE
    │ /turni → shows the current round's pairings
    │ /risultato → submits a result (win/loss/draw + game wins)
    │ /torneo_next_turn (admin) → generates the next round
    │ /drop_giocatore (admin) → forced removal with an auto-loss
    │ /correggi_risultato (admin) → overwrites/enters a result
    ▼
COMPLETED
    │ /classifica → final standings
    │ /concludi_torneo (admin) → forced conclusion
    ▼
RATING UPDATE
    └── Glicko-2 applied to every match of the tournament
```

---

## PairingEngine (`services/pairing_engine.py`)

### Swiss Algorithm

```
function generate_round(players, existing_matches, round_number):
    keep active (non-dropped) players only
    group them into score brackets, highest score first
    for each bracket:
        sort by OMW (desc), then seed (desc); round 1: shuffle instead
        pair each player with the next one they haven't played (anti-rematch)
        a player left without an opponent drops down to the next bracket
    every player still unpaired at the end gets a bye, lowest score first,
        preferring players who haven't had a bye yet
    return the list of Pairing objects (with table numbers)
```

### Rules

- **Round 1**: random pairing (shuffle)
- **Later rounds**: pairing by score bracket
- **Anti-rematch**: the same pairing is not repeated (`_existing_pairs()`)
- **Bye**: to whoever is left unpaired; usually a single player with an odd count, but more than one if
  anti-rematch leaves no legal opponent
- **Round count**: `max(1, ceil(log2(player_count)))` (`calculate_rounds()`)

### Bye Handling

- A bye is worth 3 points (like a win)
- The player with the bye is `player1`, `player2` is `NULL`
- Players who already had a bye are sorted after the others when byes are assigned (`_bye_history()`), so a
  second bye is avoided when possible

---

## StandingsCalculator (`services/standings.py`)

### Points

| Result | Points |
|---|---|
| Win | 3 |
| Draw | 1 |
| Loss | 0 |
| Bye | 3 |

### Tiebreakers (in priority order)

1. **Match Points** (total score)
2. **Opponent Match Win % (OMW)** — average of the opponents' win percentages (33% floor)
3. **Game Win % (GWP)** — percentage of games won (33% floor)
4. **Opponent Game Win % (OGW)** — average GWP of the opponents
5. **Player name** (alphabetical, ascending)

Current-round matches **with no result yet** don't count: neither as games nor toward the opponent's OMW/OGW
(byes count right away, 3 points). Until 3.6.1 they counted as a 1-1 in games, and a mid-round `/classifica`
skewed GWP and OMW; the final standings were not affected.

### Dropped Players

A player removed after the start (`/drop_giocatore`) **stays in the standings**, marked _(drop)_, with the
points from the matches already played: those matches keep counting toward their opponents' OMW/OGW, as in
Wizards tournaments. Someone who left during registration (no match played) doesn't appear. They are no
longer paired in later rounds (`PairingEngine` only gets active registrations). Matches against a dropped
player also count toward the end-of-tournament Glicko-2 rating.

Until 3.5.4 `get_standings()` passed only active registrations to the calculation while the dropped player's
matches remained: `/classifica` raised `KeyError` after any drop on a started tournament, and
`_update_ratings()` silently skipped matches against them. `compute()` now tolerates a player present only in
the matches (`stats.setdefault`) instead of failing.

### OMW Progress Bar

The OMW bar is shown in the standings as a visual indicator (10 cells, `omw_bar()`):
```
████████░░ 82.3%
```

---

## Glicko-2 Rating (`services/rating.py`)

### Parameters

| Parameter | Value |
|---|---|
| Initial rating | 1500.0 |
| Initial deviation (RD) | 350.0 |
| Initial volatility | 0.06 |
| Tau (τ) | 0.5 |
| Rating floor | 100.0 |
| Convergence threshold | 1e-6 |

### Functions

| Function | Use |
|---|---|
| `rate_1vs1(winner, loser, winner_game_wins=2, loser_game_wins=0)` | Win/loss match. Takes and returns `Rating` objects; the game-win arguments are accepted but don't affect the result (2-0 and 2-1 rate the same) |
| `rate_draw(player_a, player_b)` | Drawn match |

### Scale Conversion

`mu = (rating - 1500.0) / 173.7178`
`phi = rd / 173.7178`

### Leaderboard

The leaderboard shows `lb_rating = rating - 2 * rating_deviation` (lower bound of the 95% confidence
interval).

---

## TournamentService (`services/tournament_service.py`)

Main orchestrator, coordinating every tournament operation. The methods the cog acts on return a
`ServiceResult(ok, message, kind=None)` (`services/results.py`): `ok` tells success from failure, `message`
is the Italian text shown to the user, and `kind` (a `ResultKind`) is set only where `ok` isn't enough —
today `generate_next_round()`. The cog branches on these fields, never on the message text (until 3.6.7 it
matched phrases such as `"non trovato" in msg`, and `/iscriviti` didn't check the outcome at all).

| Method | Description |
|---|---|
| `create_tournament(name, format, max_players)` | Creates a tournament in `registration` |
| `register_player(tournament_id, discord_id, deck_name=None)` | Registers a user, deck optional (normally `None`: submitted separately). Serialized by a per-instance `asyncio.Lock`, so two simultaneous registrations can't exceed `max_players`; seed = highest seed already assigned in the tournament + 1 (dropped players included), so it stays unique after a leave. Someone who registers again after leaving keeps their seed |
| `submit_deck(tournament_id, discord_id, deck_name)` | Updates the deck of an existing registration; fails if not registered or if the tournament is no longer in `registration` |
| `unregister_player(tournament_id, discord_id)` | Voluntary leave (`/left_torneo`), `registration` only; a second attempt answers "Non sei iscritto" instead of repeating the leave |
| `start_tournament(tournament_id)` | Starts, computes the rounds, generates round 1 — **refuses** if an active registered player has `deck_name is None` |
| `submit_result(match_id, winner_tp_id, result, p1_game_wins, p2_game_wins)` | Records a result; returns `ServiceResult(ok, message)` (`services/results.py`), refuses if the match already has a result |
| `correct_result(tournament_id, round_number, table_number, winner_discord_id, winner_games, loser_games)` | Staff correction: overwrites or enters a table's result (`winner_discord_id=None` = draw, `round_number=None` = current round); `active` tournaments only; `ServiceResult` with the before → after |
| `generate_next_round(tournament_id)` | Next round or conclusion: `ok=True` for a generated round, `ok=True, kind=TOURNAMENT_COMPLETED` after the last round, `ok=False, kind=PENDING_RESULTS` while current-round results are missing, `ok=False` otherwise |
| `force_drop_player(tournament_id, discord_id)` | Removal decided by staff: in `registration` it only marks the registration as dropped (unblocks a `start_tournament()` stuck on a missing deck); in `active` it also gives the win to the opponent in the current round's pending match |
| `force_conclude_tournament(tournament_id)` | Early conclusion |
| `get_standings(tournament_id)` | Standings with names; includes dropped players who played at least one match (`StandingsEntry.dropped`) |
| `get_leaderboard(limit)` | Top N by rating |
| `_update_ratings(tournament_id)` | Glicko-2 on every match, including those against players later dropped |

Covered by end-to-end tests in `tests/tournament/test_tournament_service.py` (registration, deck
submission/resubmission, start blocked by a missing deck, start, pairing, result submission and
correction, round generation, forced drop, standings, rating update) on a temporary SQLite DB isolated per
test — no mocks on the persistence layer.

---

## Slash Commands

Every command lives in `cogs/tournament_system/cog.py`:

| Command | Access | Description |
|---|---|---|
| `/crea_torneo` | Admin | Creates a new tournament |
| `/avvia_torneo` | Admin | Starts the tournament |
| `/torneo_next_turn` | Admin | Next round |
| `/drop_giocatore` | Admin | Removes a player (active tournament or during registration) |
| `/concludi_torneo` | Admin | Forced conclusion |
| `/correggi_risultato` | Admin | Fixes or enters a match result |
| `/iscriviti` | Public | Registration (no deck) |
| `/invia_deck` | Public | Submits/updates the deck for an existing registration |
| `/iscrizioni_torneo` | Public | Who is registered and who has already submitted a deck |
| `/left_torneo` | Public | Unregisters |
| `/risultato` | Public | Submits a result |
| `/classifica` | Public | Shows the standings |
| `/turni` | Public | Current round's pairings |
| `/lista_tornei` | Public | Tournament list |
| `/leaderboard` | Public | Rating leaderboard |

### InviaDeckModal (`cog.py`)

Opened by `/invia_deck`, not by `/iscriviti` (which opens no modal today: it just registers). It requires an
existing registration — `submit_deck()` refuses otherwise. Modal with:
- `titolo` field (deck name, required)
- `deck_list` field (required, Arena decklist text)

On submit:
1. Decklist parsing
2. Artisan validation (banlist + rarity)
3. If valid: `TournamentService.submit_deck()` updates the existing registration + deck published to the
   public channel + `TOURNAMENT_DECK_SUBMITTED` log (INFO)
4. If invalid: embed with the errors, the registration and any previous deck stay unchanged,
   `TOURNAMENT_DECK_SUBMITTED` log (WARN)

Can be used repeatedly while the tournament stays in `registration`: the latest valid submission wins.

### RisultatoView (`cogs/tournament_system/cog.py`)

A single select menu from the submitter's point of view ("Vittoria 2-0 / 2-1", "Pareggio", "Sconfitta
1-2 / 0-2"), with confirm and cancel buttons. On confirm:
1. Determines the winner (or a draw) and the game wins for player1/player2
2. Calls `TournamentService.submit_result()`, which returns a `ServiceResult`
3. If `ok`: green embed in the ephemeral message, announcement in the tournament channel, INFO `MATCH_RESULT`
   log
4. If refused (typically: the opponent had already entered it): only the ephemeral message with the reason,
   **no public announcement**, WARN `MATCH_RESULT` log

### Who Enters the Result

Either player is enough: the first to enter it wins, with no confirmation from the opponent (deliberate — a
two-sided confirmation would add a click to every match and block the round if an opponent disappears). Staff
fixes a wrong result with `/correggi_risultato` (`correct_result()`), which also overwrites matches of past
rounds — the standings recompute on their own, while the pairings of later rounds already generated stay as
they are (the command warns about it). It is refused once the tournament is concluded, because the Glicko-2
rating has already been applied. It is also how a never-reported match gets its result.

Until 3.5.7 a refused second submission was still announced publicly ("ha registrato il risultato"), and
every successful result was logged as an orange `WARN`: the cog looked for `"Registrato"` capitalized while
the service returned `"Risultato registrato!"`.

---

## Discord Logs (`cogs/logger.py`, `LOG_CHANNEL_ID` channel)

| Event | Level | When |
|---|---|---|
| `TOURNAMENT_CREATED` | INFO | `/crea_torneo` |
| `REGISTRATION_CONFIRMED` | INFO | `/iscriviti` (registration, deck not submitted yet) |
| `REGISTRATION_REFUSED` | WARN | `/iscriviti` refused by the service (e.g. tournament full); the user gets the reason privately |
| `TOURNAMENT_DECK_SUBMITTED` | INFO/WARN | `/invia_deck` — INFO if the deck is valid and recorded, WARN if invalid or refused (not registered / tournament no longer in registration) |
| `SCRYFALL_UNAVAILABLE` | WARN | `/invia_deck` with Scryfall unreachable: deck not evaluated |
| `PLAYER_UNREGISTERED` | INFO | `/left_torneo` (voluntary leave) |
| `PLAYER_DROPPED` | INFO | `/drop_giocatore` (forced admin removal, during registration too) |
| `TOURNAMENT_START_BLOCKED` | WARN | `/avvia_torneo` refused (tournament not found/not in registration, fewer than 2 players, or missing decks) |
| `TOURNAMENT_STARTED` | INFO | `/avvia_torneo` succeeded — includes the participant list with each deck name (first 25, then "...and N more") |
| `MATCH_RESULT` | INFO/WARN | `/risultato` — INFO if recorded, WARN if refused (e.g. already entered) |
| `RESULT_CORRECTED` | INFO | `/correggi_risultato` (result before → after) |
| `ROUND_GENERATED` | INFO | `/torneo_next_turn` (new round) |
| `TOURNAMENT_CONCLUDED` | INFO | `/concludi_torneo` (forced conclusion) |
| `TOURNAMENT_COMPLETED` | INFO | Last round completed, tournament concluded naturally |

---

## Embeds (`utils/tournament_embeds.py`)

| Function | Content |
|---|---|
| `build_standings_embed()` | Standings with rank, name (marked _(drop)_ if dropped), points, OMW bar, record |
| `build_pairings_embed()` | Pairings with table number and players, byes at the bottom |
| `build_start_embed()` | Tournament start announcement with total rounds |
| `build_top8_embed()` | Top 8 bracket (quarterfinals onward); implemented but not called by any command yet |

---

## Utilities (`utils/tournament_logic.py`)

| Function | Description |
|---|---|
| `omw_bar(pct)` | Text OMW progress bar, 10 cells + percentage |
| `rank_label(position)` | Medal for positions 1-3 (🥇🥈🥉), `"N."` otherwise |
| `split_into_columns(items)` | Splits a list into two columns, the left one taking the extra item |
| `split_field_value(lines, max_chars=1000)` | Splits lines into chunks of at most `max_chars`, for embed fields (1024 limit) |
