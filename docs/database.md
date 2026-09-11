# Database

## Panoramica

ClepshydraBot utilizza **SQLite** come database relazionale, gestito tramite **SQLAlchemy 2.0** con driver asincrono **aiosqlite**. La scelta di SQLite è dettata dai vincoli hardware (1 GB RAM, nessun processo separato).

---

## Engine e Sessioni (`database/engine.py`)

| Funzione | Descrizione |
|---|---|
| `init_db()` | Crea engine, tabelle, esegue migrazioni, importa banlist seed |
| `close_db()` | Dispone l'engine (chiamata allo shutdown) |
| `get_session()` | Restituisce `AsyncSession` dal sessionmaker |

### Migrazioni Automatiche

All'avvio, `init_db()` esegue in ordine:

1. **`_migrate_banlist()`** — importa `cards.txt` in `banned_cards` se il DB è vuoto
2. **`_migrate_schema()`** — aggiunge le colonne mancanti elencate in `_SCHEMA_MIGRATIONS`
   (tabella, colonna, DDL):
   - `tournament_players.deck_name`
   - `matches.p1_game_wins`, `matches.p2_game_wins`
   - `users.rating`, `users.rating_deviation`, `users.rating_volatility`, `users.rating_matches`,
     `users.last_rated_at`

   Per ogni voce, verifica esplicitamente se la colonna esiste già via `PRAGMA table_info(<tabella>)`
   prima di eseguire l'`ALTER TABLE` — non si affida più a un `try/except Exception: pass` generico che
   avrebbe nascosto anche errori reali (permessi, disco pieno, colonna con tipo incompatibile). Se
   l'`ALTER TABLE` fallisce per un motivo diverso da "colonna già esistente" (che ora non può più
   verificarsi, essendo controllato a monte), l'errore viene stampato su stdout con prefisso `ERRORE
   migrazione:` invece di essere ignorato silenziosamente — l'avvio del bot non si interrompe comunque,
   per non bloccare l'intero servizio per una singola colonna non applicata.

   Per aggiungere una nuova migrazione in futuro, basta aggiungere una tupla `(tabella, colonna, ddl)` a
   `_SCHEMA_MIGRATIONS` in `database/engine.py` — non serve toccare `_migrate_schema()`.

---

## Modelli ORM (`database/models.py`)

### Tabella: `users`

| Colonna | Tipo | Vincoli | Descrizione |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | ID interno |
| `discord_id` | Integer | UNIQUE, NOT NULL, INDEX | ID Discord |
| `nickname_arena` | String(100) | NULLABLE | Nickname MTGA |
| `nome` | String(100) | NULLABLE | Nome visualizzato |
| `created_at` | DateTime | DEFAULT now | Data creazione |
| `rating` | Float | DEFAULT 1500.0 | Rating Glicko-2 |
| `rating_deviation` | Float | DEFAULT 350.0 | Deviazione rating |
| `rating_volatility` | Float | DEFAULT 0.06 | Volatilità Glicko-2 |
| `rating_matches` | Integer | DEFAULT 0 | Match giocati |
| `last_rated_at` | DateTime | NULLABLE | Ultimo aggiornamento |

Relazioni: `tournament_players` → TournamentPlayer

### Tabella: `tournaments`

| Colonna | Tipo | Vincoli | Descrizione |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | ID torneo |
| `name` | String(200) | NOT NULL | Nome torneo |
| `format` | String(50) | DEFAULT 'Artisan' | Formato |
| `status` | Enum | DEFAULT 'registration' | registration/active/completed |
| `max_players` | Integer | NULLABLE | Cap giocatori |
| `round_count` | Integer | NULLABLE | Round totali |
| `created_at` | DateTime | DEFAULT now | |
| `started_at` | DateTime | NULLABLE | |
| `ended_at` | DateTime | NULLABLE | |

Relazioni: `players` → TournamentPlayer, `matches` → Match

### Tabella: `tournament_players`

| Colonna | Tipo | Vincoli | Descrizione |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `tournament_id` | Integer | FK → tournaments.id | |
| `user_id` | Integer | FK → users.id | |
| `joined_at` | DateTime | DEFAULT now | |
| `dropped` | Boolean | DEFAULT False | Ritirato |
| `seed` | Integer | NULLABLE | Seed pairing |
| `deck_name` | String(200) | NULLABLE | Nome deck (migrazione) |

Relazioni: `tournament` → Tournament, `user` → User, `matches_as_player1/2` → Match

### Tabella: `matches`

| Colonna | Tipo | Vincoli | Descrizione |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `tournament_id` | Integer | FK → tournaments.id | |
| `round_number` | Integer | NOT NULL | Round |
| `player1_id` | Integer | FK → tournament_players.id | |
| `player2_id` | Integer | FK → tournament_players.id, NULLABLE | NULL = bye |
| `winner_id` | Integer | FK → tournament_players.id, NULLABLE | |
| `result` | Enum | NULLABLE | win/loss/draw |
| `table_number` | Integer | NULLABLE | Tavolo |
| `p1_game_wins` | Integer | NULLABLE | Game vinti P1 (migrazione) |
| `p2_game_wins` | Integer | NULLABLE | Game vinti P2 (migrazione) |

Relazioni: `tournament` → Tournament, `player1/2` → TournamentPlayer

### Tabella: `banned_cards`

| Colonna | Tipo | Vincoli | Descrizione |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | |
| `card_name` | String(200) | UNIQUE, NOT NULL, INDEX | Nome carta |
| `format` | String(50) | DEFAULT 'Artisan' | Formato |
| `created_at` | DateTime | DEFAULT now | |

### Enums

```python
class TournamentStatus(str, enum.Enum):
    REGISTRATION = "registration"
    ACTIVE = "active"
    COMPLETED = "completed"

class MatchResult(str, enum.Enum):
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"
```

---

## Repository Pattern

### BaseRepository (`repositories/base.py`)

Repository generico con CRUD base:

| Metodo | Descrizione |
|---|---|
| `get_by_id(id)` | Fetch per PK |
| `list_all()` | Tutti i record |
| `add(model)` | Insert + commit + refresh |
| `delete(model)` | Delete + commit |
| `count()` | Conteggio record |

### UserRepository (`repositories/user_repository.py`)

| Metodo | Descrizione |
|---|---|
| `get_by_discord_id(discord_id)` | Fetch per ID Discord |
| `get_or_create(discord_id, nickname_arena, nome)` | Find o create |
| `get_leaderboard(limit)` | Top N per rating |

### TournamentRepository (`repositories/tournament_repository.py`)

| Metodo | Descrizione |
|---|---|
| `get_by_status(status)` | Tornei filtrati per stato |
| `get_by_id(id)` | Fetch per PK |
| `get_with_players(id)` | Eager load con giocatori |
| `get_active_tournaments()` | Tornei in corso |

### TournamentPlayerRepository

| Metodo | Descrizione |
|---|---|
| `get_by_tournament(tournament_id)` | Giocatori attivi (eager load user) |
| `count_by_tournament(tournament_id)` | Conteggio iscritti |

### MatchRepository

| Metodo | Descrizione |
|---|---|
| `get_by_tournament(tournament_id)` | Match di un torneo (eager load) |
| `get_current_round(tournament_id)` | Round più alto giocato |
| `get_pairings_for_round(tournament_id, round_num)` | Pairing di un round |
| `existing_pairings(tournament_id)` | Pairings già avvenuti (per anti-rematch) |

### BanlistRepository (`repositories/banlist_repository.py`)

| Metodo | Descrizione |
|---|---|
| `get_all_for_format(format)` | Set di carte bannate (lowercase) |
| `add_card(card_name, format)` | Aggiunge carta |
| `remove_card(card_name)` | Rimuovi per nome esatto |
| `count()` | Conteggio banlist |
| `import_from_file(path)` | Bulk import da txt (solo se DB vuoto) |

---

## Testing

`tests/tournament/test_tournament_service.py` esercita l'intero stack DB (engine, sessioni, repository, migrazioni) contro un file SQLite temporaneo, isolato per ogni test:

1. Fixture `isolated_db` (`tmp_path` + `monkeypatch`) punta `database.engine.DB_PATH` a un file temporaneo e azzera i globali `_engine`/`_async_session_maker`.
2. Ogni test esegue `init_db()` → logica → `close_db()` in un **unico** `asyncio.run()`: `aiosqlite` lega le connessioni al loop che le ha create, quindi non si possono distribuire setup/uso/teardown su piu' event loop separati.
3. Non ci sono mock: le query SQLAlchemy girano davvero contro SQLite, comprese le migrazioni `ALTER TABLE` di `_migrate_schema()`.
