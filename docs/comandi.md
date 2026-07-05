# Riferimento Comandi

## Comandi Pubblici

### Presentazioni

| Comando | Descrizione | Modalità |
|---|---|---|
| `/presentati` | Avvia wizard presentazione multi-step | Modal + Select + Preview |

### Validazione Mazzi

| Comando | Descrizione | Modalità |
|---|---|---|
| `/artisan_check_deck` | Verifica legalità mazzo Artisan | Modal (decklist testuale) |

### Tornei — Iscrizione

| Comando | Descrizione | Sinonimi |
|---|---|---|
| `/iscriviti [torneo_id]` | Iscrizione al torneo con validazione deck | `/register` |
| `/left_torneo [torneo_id]` | Disiscrizione prima dell'avvio | `/unregister` |

### Tornei — Partecipazione

| Comando | Descrizione |
|---|---|
| `/risultato [torneo]` | Invia risultato match (select menu game wins) |
| `/classifica [torneo_id]` | Visualizza classifica con punti e OMW |
| `/turni [torneo_id]` | Pairing del round corrente |

### Tornei — Informazioni

| Comando | Descrizione |
|---|---|
| `/lista_tornei` | Elenco di tutti i tornei con ID, nome, stato, giocatori |
| `/leaderboard [limite]` | Classifica rating Glicko-2 (default: 10) |
| `/banlist` | Lista carte bannate in embed paginato |

---

## Comandi Admin (ruolo `Staff`)

### Gestione Tornei

| Comando | Descrizione |
|---|---|
| `/crea_torneo` | Apre modale per creare nuovo torneo (nome, formato, max player) |
| `/avvia_torneo [torneo]` | Avvia registrazione → stato attivo, genera round 1 |
| `/torneo_next_turn [torneo]` | Genera prossimo round o completa torneo |
| `/drop_giocatore <giocatore> [torneo]` | Rimozione forzata con auto-loss |
| `/concludi_torneo [torneo]` | Conclusione anticipata con rating update |

### Gestione Banlist

| Comando | Descrizione |
|---|---|
| `/banlist_aggiungi <carta>` | Aggiunge carta alla banlist |
| `/banlist_rimuovi <carta>` | Rimuove carta dalla banlist |

### Manutenzione

| Comando | Descrizione |
|---|---|
| `/update_spg_overrides` | Scansione Scryfall per aggiornare override SPG (Special Guest) |

---

## Dettaglio Implementazione

### Location File

| Comando | File | Linea |
|---|---|---|
| `/presentati` | `cogs/presentation/cog.py` | 45 |
| `/artisan_check_deck` | `cogs/deck_validation/__init__.py` | 67 |
| `/crea_torneo` | `cogs/tournament_system/cog.py` | 489 |
| `/avvia_torneo` | `cogs/tournament_system/cog.py` | 500 |
| `/torneo_next_turn` | `cogs/tournament_system/cog.py` | 684 |
| `/drop_giocatore` | `cogs/tournament_system/cog.py` | 586 |
| `/concludi_torneo` | `cogs/tournament_system/cog.py` | 637 |
| `/iscriviti` | `cogs/tournament_system/cog.py` | 846 |
| `/left_torneo` | `cogs/tournament_system/cog.py` | 885 |
| `/risultato` | `cogs/tournament_system/cog.py` | 926 |
| `/classifica` | `cogs/tournament_system/cog.py` | 1003 |
| `/turni` | `cogs/tournament_system/cog.py` | 1106 |
| `/lista_tornei` | `cogs/tournament_system/cog.py` | 797 |
| `/leaderboard` | `cogs/tournament_system/cog.py` | 1120 |
| `/banlist` | `cogs/tournament_system/cog.py` | 1172 |
| `/banlist_aggiungi` | `cogs/tournament_system/cog.py` | 1216 |
| `/banlist_rimuovi` | `cogs/tournament_system/cog.py` | 1246 |
| `/update_spg_overrides` | `cogs/spg_override_updater.py` | 26 |

---

## Helper e Utility

### TournamentSystemCog — Helper

| Helper | Descrizione | Linea |
|---|---|---|
| `_get_tournament(interaction, torneo_id)` | Autocomplete + fetch torneo | 464 |
| `_get_tournament_autocomplete()` | Autocomplete per parametri torneo | 440 |

### Permessi

`is_admin()` check (`utils/permissions.py:5`):
- Verifica che l'utente abbia il ruolo `ADMIN_ROLE` (default: `Staff`)
- Usato come decoratore su comandi admin: `@app_commands.check(is_admin)`
