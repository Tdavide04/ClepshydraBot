# Sistema Tornei Swiss

## Panoramica

Il sistema tornei gestisce l'intero ciclo di vita di un torneo Swiss per Magic: The Gathering Arena. Supporta registrazione, pairing automatico, registrazione risultati, classifiche con tiebreaker e rating Glicko-2.

---

## Struttura

```
services/
├── tournament_service.py   # Orchestratore: coordina tutte le operazioni
├── pairing_engine.py       # Algoritmo Swiss pairing
├── standings.py            # Classifiche con tiebreaker
└── rating.py               # Sistema rating Glicko-2

cogs/tournament_system/
└── cog.py                  # 17 comandi slash + modali + view

utils/
├── tournament_logic.py     # Utility (barra OMW, label rank, colonne)
└── tournament_embeds.py    # Builder embed (classifica, pairing, start, top8)
```

---

## Ciclo di Vita del Torneo

```
CREAZIONE (admin)
    │ /crea_torneo → nome, formato, max_giocatori
    ▼
REGISTRAZIONE
    │ /iscriviti → registrazione diretta, nessun mazzo richiesto
    │ /invia_deck → InviaDeckModal (deck validation + submit), ripetibile
    │ /iscrizioni_torneo → chi è iscritto e chi ha già inviato il mazzo
    │ /left_torneo → uscita volontaria
    ▼
AVVIO (admin)
    │ /avvia_torneo → bloccato se un iscritto attivo non ha ancora
    │                 inviato un mazzo valido (elenca chi manca)
    │               → altrimenti: calcolo round, pairing round 1
    ▼
ATTIVO
    │ /turni → visualizza pairing round corrente
    │ /risultato → submit risultato (win/loss/draw + game wins)
    │ /torneo_next_turn (admin) → genera prossimo round
    │ /drop_giocatore (admin) → rimozione forzata
    ▼
COMPLETATO
    │ /classifica → classifica finale
    │ /concludi_torneo (admin) → conclusione forzata
    ▼
AGGIORNAMENTO RATING
    └── Glicko-2 applicato a tutti i match del torneo
```

---

## PairingEngine (`services/pairing_engine.py`)

### Algoritmo Swiss

```
function generate_round(players, existing_matches, round_num):
    if round_num == 1:
        shuffle players
        pair consecutively: (1,2), (3,4), ...
    else:
        sort players by score (desc)
        group by score bracket
        for each bracket:
            sort by OMW (desc)
            pair consecutive, skip if already played (anti-rematch)
        handle unpaired players (slide down to next bracket)
        assign bye to lowest-ranked player if odd count
    return list of Match objects
```

### Regole

- **Round 1**: pairing casuale (shuffle)
- **Round successivi**: pairing per bracket di punteggio
- **Anti-rematch**: stesso pairing non ripetuto
- **Bye**: assegnato al giocatore con punteggio più basso tra quelli che non hanno già avuto bye (se numero dispari)
- **Calcolo round**: `ceil(log2(numero_giocatori))`

### Bye Handling

- Il bye assegna 3 punti (come una vittoria)
- Il giocatore con bye è `player1`, `player2` è `NULL`
- `winner_id` = `player1_id` (automatico)
- Un giocatore non può ricevere bye più di una volta se possibile

---

## StandingsCalculator (`services/standings.py`)

### Punteggi

| Risultato | Punti |
|---|---|
| Vittoria | 3 |
| Pareggio | 1 |
| Sconfitta | 0 |
| Bye | 3 |

### Tiebreaker (in ordine di priorità)

1. **Match Points** (punteggio totale)
2. **Opponent Match Win % (OMW)** — media delle percentuali di vittoria degli avversari (floor 33%)
3. **Game Win % (GWP)** — percentuale di game vinti (floor 33%)
4. **Opponent Game Win % (OGW)** — media GWP degli avversari
5. **Nome giocatore** (ordine alfabetico, ascendente)

### OMW Progress Bar

La barra OMW è visualizzata nelle classifiche come indicatore visuale:
```
████████░░ 82.3%
```

---

## Rating Glicko-2 (`services/rating.py`)

### Parametri

| Parametro | Valore |
|---|---|
| Rating iniziale | 1500.0 |
| Deviazione iniziale (RD) | 350.0 |
| Volatilità iniziale | 0.06 |
| Tau (τ) | 0.5 |
| Rating floor | 100.0 |
| Soglia convergenza | 1e-6 |

### Funzioni

| Funzione | Utilizzo |
|---|---|
| `rate_1vs1(rating1, rd1, vol1, rating2, rd2, vol2, score)` | Match win/loss con game score |
| `rate_draw(rating1, rd1, vol1, rating2, rd2, vol2)` | Match pareggio |

### Conversione scale

`mu = (rating - 1500.0) / 173.7178`  
`phi = rd / 173.7178`

### Leaderboard

La leaderboard mostra `lb_rating = rating - 2 * rating_deviation` (limite inferiore dell'intervallo di confidenza al 95%).

---

## TournamentService (`services/tournament_service.py`)

Metodo principale orchestratore che coordina tutte le operazioni del torneo.

| Metodo | Descrizione |
|---|---|
| `create_tournament(name, format, max_players)` | Crea torneo in stato `registration` |
| `register_player(tournament_id, discord_id, deck_name=None)` | Registra utente, mazzo opzionale (di norma `None`: si invia separatamente) |
| `submit_deck(tournament_id, discord_id, deck_name)` | Aggiorna il mazzo di un'iscrizione già esistente; fallisce se non iscritto o se il torneo non è più in `registration` |
| `start_tournament(tournament_id)` | Avvia, calcola round, genera round 1 — **rifiuta** se un iscritto attivo ha `deck_name is None` |
| `submit_result(match_id, winner_id, p1_wins, p2_wins)` | Registra risultato |
| `generate_next_round(tournament_id)` | Round successivo o conclusione |
| `force_drop_player(tournament_id, discord_id)` | Rimozione con auto-loss |
| `force_conclude_tournament(tournament_id)` | Conclusione anticipata |
| `get_standings(tournament_id)` | Classifica con nomi |
| `get_leaderboard(limit)` | Top N rating |
| `_update_ratings(tournament_id)` | Glicko-2 su tutti i match |

Coperto da test end-to-end in `tests/tournament/test_tournament_service.py` (iscrizione, invio/reinvio mazzo, blocco avvio se manca un mazzo, avvio, pairing, submit risultato, generazione round, drop forzato, standings, aggiornamento rating) su un DB SQLite temporaneo isolato per test — nessun mock sul layer di persistenza.

---

## Comandi Slash

Tutti i comandi in `cogs/tournament_system/cog.py`:

| Comando | Accesso | Descrizione |
|---|---|---|
| `/crea_torneo` | Admin | Crea nuovo torneo |
| `/avvia_torneo` | Admin | Inizia torneo |
| `/torneo_next_turn` | Admin | Prossimo round |
| `/drop_giocatore` | Admin | Rimuovi giocatore |
| `/concludi_torneo` | Admin | Concludi forzatamente |
| `/iscriviti` | Pubblico | Iscrizione (senza mazzo) |
| `/invia_deck` | Pubblico | Invia/aggiorna il mazzo per un'iscrizione esistente |
| `/iscrizioni_torneo` | Pubblico | Chi è iscritto e chi ha già inviato il mazzo |
| `/left_torneo` | Pubblico | Disiscrizione |
| `/risultato` | Pubblico | Invia risultato |
| `/classifica` | Pubblico | Visualizza classifica |
| `/turni` | Pubblico | Pairing round corrente |
| `/lista_tornei` | Pubblico | Lista tornei |
| `/leaderboard` | Pubblico | Classifica rating |
| `/banlist` | Pubblico | Lista carte bannate |
| `/banlist_aggiungi` | Admin | Aggiungi carta bannata |
| `/banlist_rimuovi` | Admin | Rimuovi carta bannata |

### InviaDeckModal (`cog.py`)

Invocato da `/invia_deck`, non da `/iscriviti` (che oggi non apre nessun modal: registra e basta).
Richiede un'iscrizione già esistente — `submit_deck()` rifiuta altrimenti. Modal con:
- Campo `titolo` (nome mazzo, obbligatorio)
- Campo `deck_list` (obbligatorio, testo Arena decklist)

All'invio:
1. Parsing decklist
2. Validazione Artisan (banlist + rarità)
3. Se valido: `TournamentService.submit_deck()` aggiorna l'iscrizione esistente + pubblicazione deck su
   canale pubblico + log `TOURNAMENT_DECK_SUBMITTED` (INFO)
4. Se invalido: embed con errori, l'iscrizione/il mazzo precedente restano invariati, log
   `TOURNAMENT_DECK_SUBMITTED` (WARN)

Richiamabile più volte finché il torneo resta in `registration`: l'ultimo invio valido sovrascrive.

### RisultatoView (`cog.py:258-430`)

Select menu per:
- `player1_wins` (0-2)
- `player2_wins` (0-2)

Con pulsante conferma che:
1. Determina vincitore (o pareggio)
2. Chiama `TournamentService.submit_result()`
3. Pubblica risultato su canale torneo
4. Logga l'evento

---

## Log su Discord (`cogs/logger.py`, canale `LOG_CHANNEL_ID`)

| Evento | Livello | Quando |
|---|---|---|
| `TOURNAMENT_CREATED` | INFO | `/crea_torneo` |
| `REGISTRATION_CONFIRMED` | INFO | `/iscriviti` (registrazione, mazzo non ancora inviato) |
| `TOURNAMENT_DECK_SUBMITTED` | INFO/WARN | `/invia_deck` — INFO se il mazzo è valido e registrato, WARN se non valido o rifiutato (non iscritto / torneo non più in registrazione) |
| `PLAYER_UNREGISTERED` | INFO | `/left_torneo` (uscita volontaria) |
| `PLAYER_DROPPED` | INFO | `/drop_giocatore` (rimozione forzata admin) |
| `TOURNAMENT_START_BLOCKED` | WARN | `/avvia_torneo` rifiutato (torneo non trovato/non in registrazione, meno di 2 giocatori, o mazzi mancanti) |
| `TOURNAMENT_STARTED` | INFO | `/avvia_torneo` riuscito — include l'elenco partecipanti e il nome del mazzo di ciascuno (primi 25, poi "...e altri N") |
| `MATCH_RESULT` | INFO | `/risultato` confermato |
| `ROUND_GENERATED` | INFO | `/torneo_next_turn` (nuovo round) |
| `TOURNAMENT_CONCLUDED` | INFO | `/concludi_torneo` (conclusione forzata) |
| `TOURNAMENT_COMPLETED` | INFO | Ultimo round completato, torneo concluso naturalmente |
| `BANLIST_ADD` / `BANLIST_REMOVE` | INFO | `/banlist_aggiungi` / `/banlist_rimuovi` |

---

## Embed (`utils/tournament_embeds.py`)

| Funzione | Contenuto |
|---|---|
| `build_standings_embed()` | Classifica con rank, nome, punti, OMW bar, record |
| `build_pairings_embed()` | Pairing con table number, giocatori, link profilo |
| `build_start_embed()` | Annuncio inizio torneo con round totali |
| `build_top8_embed()` | Bracket top 8 (da implementare) |

---

## Utility (`utils/tournament_logic.py`)

| Funzione | Descrizione |
|---|---|
| `omw_bar(omw, width=12)` | Genera barra progresso OMW testuale |
| `rank_label(rank)` | Restituisce medaglia/testo per posizione (1°🥇, 2°🥈, 3°🥉) |
| `split_into_columns(items, max_rows)` | Divide lista in colonne per embed |
| `split_field_value(items, max_length=1024)` | Tronca valori campo embed a 1024 caratteri |
