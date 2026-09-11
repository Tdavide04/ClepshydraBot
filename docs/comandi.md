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
| `/iscriviti [torneo_id]` | Iscrizione al torneo (nessun mazzo richiesto qui) | `/register` |
| `/invia_deck [torneo_id]` | Invia/aggiorna il mazzo per un'iscrizione già fatta — richiesto prima dell'avvio, ripetibile | — |
| `/iscrizioni_torneo [torneo_id]` | Elenco iscritti con stato mazzo (✅ inviato / ⏳ in attesa) | — |
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
| `/avvia_torneo [torneo]` | Avvia registrazione → stato attivo, genera round 1 — rifiuta se un iscritto attivo non ha ancora inviato un mazzo valido |
| `/torneo_next_turn [torneo]` | Genera prossimo round o completa torneo |
| `/drop_giocatore <giocatore> [torneo]` | Rimozione forzata con auto-loss |
| `/concludi_torneo [torneo]` | Conclusione anticipata con rating update |

### Gestione Banlist

| Comando | Descrizione |
|---|---|
| `/banlist_aggiungi <carta>` | Aggiunge carta alla banlist (invalida subito la cache in memoria) |
| `/banlist_rimuovi <carta>` | Rimuove carta dalla banlist (invalida subito la cache in memoria) |

### Manutenzione

| Comando | Descrizione |
|---|---|
| `/forced_rarity_refresh` | Forza subito un controllo degli override SPG (gira anche da solo ogni settimana — vedi `docs/caching.md`) |
| `/forced_event_schedule_check` | Forza subito un ricontrollo della pagina "Event Schedule" Arena più recente, ignorando l'ultimo `lastmod` salvato (gira anche da solo ogni giorno — vedi `docs/caching.md`) |
| `/invalidate_card_cache <carta>` | Rimuove una carta dalla cache Scryfall, forzando un ricontrollo completo alla prossima validazione (senza attendere il TTL di 30 giorni) |

---

## Dettaglio Implementazione

### Location File

| Comando | File | Linea |
|---|---|---|
| `/presentati` | `cogs/presentation/cog.py` | 45 |
| `/artisan_check_deck` | `cogs/deck_validation/__init__.py` | 67 |
| `/crea_torneo` | `cogs/tournament_system/cog.py` | 507 |
| `/avvia_torneo` | `cogs/tournament_system/cog.py` | 521 |
| `/torneo_next_turn` | `cogs/tournament_system/cog.py` | 719 |
| `/drop_giocatore` | `cogs/tournament_system/cog.py` | 622 |
| `/concludi_torneo` | `cogs/tournament_system/cog.py` | 672 |
| `/iscriviti` | `cogs/tournament_system/cog.py` | 880 |
| `/invia_deck` | `cogs/tournament_system/cog.py` | 936 |
| `/iscrizioni_torneo` | `cogs/tournament_system/cog.py` | 975 |
| `/left_torneo` | `cogs/tournament_system/cog.py` | 1025 |
| `/risultato` | `cogs/tournament_system/cog.py` | 1071 |
| `/classifica` | `cogs/tournament_system/cog.py` | 1148 |
| `/turni` | `cogs/tournament_system/cog.py` | 1251 |
| `/lista_tornei` | `cogs/tournament_system/cog.py` | 828 |
| `/leaderboard` | `cogs/tournament_system/cog.py` | 1265 |
| `/banlist` | `cogs/tournament_system/cog.py` | 1314 |
| `/banlist_aggiungi` | `cogs/tournament_system/cog.py` | 1360 |
| `/banlist_rimuovi` | `cogs/tournament_system/cog.py` | 1391 |
| `/forced_rarity_refresh` | `cogs/spg_override_updater.py` | 26 |
| `/forced_event_schedule_check` | `cogs/arena_event_schedule_updater.py` | 22 |
| `/invalidate_card_cache` | `cogs/spg_override_updater.py` | 97 |

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
