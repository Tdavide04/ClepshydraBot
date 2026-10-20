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
| `/risultato [torneo]` | Invia risultato match (select menu game wins). Vale il primo dei due giocatori che lo inserisce: un secondo invio viene rifiutato in privato, senza annuncio pubblico — se il risultato è sbagliato lo corregge lo staff con `/correggi_risultato` |
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
| `/drop_giocatore <giocatore> [torneo]` | Rimozione forzata: durante le iscrizioni toglie l'iscritto (sblocca `/avvia_torneo` se non ha mai inviato il mazzo), a torneo attivo con auto-loss |
| `/concludi_torneo [torneo]` | Conclusione anticipata con rating update |
| `/correggi_risultato <tavolo> <esito> [vincitore] [turno] [torneo]` | Sovrascrive (o inserisce, se manca) il risultato di una partita del torneo in corso: `esito` 2-0 / 2-1 / pareggio, `vincitore` obbligatorio tranne che per il pareggio, `turno` di default quello in corso. Anche round passati: la classifica si ricalcola, gli abbinamenti già generati restano. Rifiutato a torneo concluso (rating già calcolato). Annuncio pubblico + log `RESULT_CORRECTED` |

### Gestione Banlist

| Comando | Descrizione |
|---|---|
| `/banlist_aggiungi <carta>` | Aggiunge carta alla banlist (invalida subito la cache in memoria) |
| `/banlist_rimuovi <carta>` | Rimuove carta dalla banlist (invalida subito la cache in memoria) |

### Manutenzione

| Comando | Descrizione |
|---|---|
| `/forced_rarity_refresh` | Forza subito un controllo degli override SPG (gira anche da solo ogni settimana — vedi `docs/caching.md`) |
| `/forced_event_schedule_check` | Forza subito un ricontrollo della pagina "Event Schedule" Arena più recente, ignorando l'ultimo `lastmod` salvato (gira anche da solo ogni 2 ore — vedi `docs/caching.md`); posta l'immagine calendario sia nel canale log sia nel canale community |
| `/forced_ban_announcement_check` | Forza subito un ricontrollo dell'ultimo Banned and Restricted Announcement, ignorando l'ultimo `lastmod` salvato (gira anche da solo ogni 2 ore — vedi `docs/caching.md`); se ci sono modifiche reali, posta sia nel canale log sia nel canale community (solo nel canale log se quell'annuncio era già stato notificato alla community) — solo notifica, non tocca mai la banlist Artisan |
| `/invalidate_card_cache <carta>` | Rimuove una carta dalla cache Scryfall, forzando un ricontrollo completo alla prossima validazione (senza attendere il TTL di 30 giorni) |

---

## Dettaglio Implementazione

### Location File

| Comando | File | Linea |
|---|---|---|
| `/presentati` | `cogs/presentation/cog.py` | 48 |
| `/artisan_check_deck` | `cogs/deck_validation/__init__.py` | 58 |
| `/crea_torneo` | `cogs/tournament_system/cog.py` | 544 |
| `/avvia_torneo` | `cogs/tournament_system/cog.py` | 558 |
| `/torneo_next_turn` | `cogs/tournament_system/cog.py` | 831 |
| `/drop_giocatore` | `cogs/tournament_system/cog.py` | 659 |
| `/concludi_torneo` | `cogs/tournament_system/cog.py` | 784 |
| `/correggi_risultato` | `cogs/tournament_system/cog.py` | 718 |
| `/iscriviti` | `cogs/tournament_system/cog.py` | 992 |
| `/invia_deck` | `cogs/tournament_system/cog.py` | 1048 |
| `/iscrizioni_torneo` | `cogs/tournament_system/cog.py` | 1087 |
| `/left_torneo` | `cogs/tournament_system/cog.py` | 1137 |
| `/risultato` | `cogs/tournament_system/cog.py` | 1183 |
| `/classifica` | `cogs/tournament_system/cog.py` | 1260 |
| `/turni` | `cogs/tournament_system/cog.py` | 1363 |
| `/lista_tornei` | `cogs/tournament_system/cog.py` | 940 |
| `/leaderboard` | `cogs/tournament_system/cog.py` | 1377 |
| `/banlist` | `cogs/tournament_system/cog.py` | 1426 |
| `/banlist_aggiungi` | `cogs/tournament_system/cog.py` | 1472 |
| `/banlist_rimuovi` | `cogs/tournament_system/cog.py` | 1503 |
| `/forced_rarity_refresh` | `cogs/spg_override_updater.py` | 31 |
| `/forced_event_schedule_check` | `cogs/arena_event_schedule_updater.py` | 27 |
| `/forced_ban_announcement_check` | `cogs/ban_announcement_updater.py` | 27 |
| `/invalidate_card_cache` | `cogs/spg_override_updater.py` | 103 |

---

## Helper e Utility

### TournamentSystemCog — Helper

| Helper | Descrizione | Linea |
|---|---|---|
| `_get_tournament(interaction, torneo_id)` | Autocomplete + fetch torneo | 464 |
| `_get_tournament_autocomplete()` | Autocomplete per parametri torneo | 440 |

### Permessi

`is_admin()` check (`utils/permissions.py`):
- Verifica che l'utente abbia il ruolo `ADMIN_ROLE` (default: `Staff`)
- Usato come decoratore su comandi admin: `@app_commands.check(is_admin)`
