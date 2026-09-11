# Changelog

## 1.9.0 (2026-09-11)

### Fixed
- **Bug confermato in produzione**: `update_spg_overrides()` usava `processed_sets` per marcare l'intero
  set `SPG` come "fatto per sempre" dopo la prima scansione riuscita. Sbagliato: Scryfall usa un unico set
  code `SPG` che cresce nel tempo (nuove Special Guests con quasi ogni set principale, ~4-8 settimane in
  media — vedi ricerca in `docs/roadmap-miglioramenti.md`). Il file reale del repo aveva già
  `processed_sets: ["SPG"]` con 37 override — ogni run successivo, anche manuale, era un no-op silenzioso
  da mesi, senza alcun modo di sbloccarlo se non editando il JSON a mano
- `utils/arena_overrides.py`: sostituito `processed_sets` (flag per l'intero set) con `checked_cards`
  (elenco per set code delle singole carte già valutate, con o senza override). Una scansione salta solo
  le carte già viste, non l'intero set — i run successivi al primo costano solo le carte nuove dall'ultimo
  controllo. Un file nel vecchio formato non blocca più nulla: `checked_cards` mancante viene trattato come
  vuoto, quindi la prima scansione dopo l'aggiornamento riscansiona tutto una volta (recupero automatico,
  nessuna migrazione manuale richiesta). File dati del repo (`data/arena_rarity_data.json`) migrato allo
  stesso modo, `overrides` esistenti preservati
- Aggiunto `_update_lock` (`asyncio.Lock()`): evita che il nuovo task automatico e un refresh manuale
  sovrascrivano il JSON contemporaneamente se capitano nello stesso momento

### Added
- `periodic_spg_refresh_loop(bot)`: nuovo task in background (avviato da `main.py` insieme a
  `periodic_save_loop()`) che chiama `update_spg_overrides()` ogni 7 giorni senza intervento admin — primo
  giro subito all'avvio, non aspetta il primo intervallo. Logga su Discord (`SPG_OVERRIDES_UPDATED`, INFO)
  solo quando trova davvero qualcosa di nuovo
- `/forced_rarity_refresh` (rinominato da `/update_spg_overrides`): ora logga anche su Discord oltre alla
  risposta ephemeral all'admin, coerente con `BANLIST_ADD`/`BANLIST_REMOVE`
- `tests/deck_validation/test_arena_overrides.py`: 4 test, incluso uno che riproduce esattamente il bug
  del vecchio formato trovato in produzione (JSON con `processed_sets` legacy non deve più bloccare la
  scansione). Suite totale: 108 → 112

## 1.8.0 (2026-09-11)

### Added
- `Dockerfile` multi-stage: stage `builder` installa le dipendenze in un venv isolato, lo stage finale
  copia solo il venv già pronto + il codice applicativo, gira come utente non-root (`clepshydra`, uid
  1000)
- `docker-compose.yml`: `restart: unless-stopped`, `env_file: .env` (mai copiato nell'immagine), volume
  Docker nominato `clepshydra-data` su `/app/data` per la persistenza tra riavvii
- `.dockerignore`: esclude `.git`, `data/` (mai nell'immagine — solo runtime/cache), `.env`, test/docs/
  legacy dal contesto di build
- README "Quick Start": sezione Docker come alternativa all'installazione diretta

Validato con build e avvio reali (non solo scrittura dei file): immagine costruita con successo,
container avviato come utente non-root con `/app/data` scrivibile, tutte le dipendenze importabili,
`docker compose up` con token Discord invalido riproduce correttamente il comportamento `FATAL:` +
`sys.exit(1)` già documentato per `pm2`, e `restart: unless-stopped` riavvia automaticamente il
container come atteso. Immagini/volumi/container di test rimossi dopo la verifica.

## 1.7.1 (2026-09-11)

### Fixed
- Sanati i 54 problemi di lint pre-esistenti (`ruff check .`): import inutilizzati, f-string senza
  placeholder e import multipli sulla stessa riga corretti con `ruff --fix` (diff rivisto a mano);
  statement multipli su una riga (`if x: y`) separati manualmente; in
  `repositories/tournament_repository.py`, `TournamentPlayer.dropped == False` sostituito con
  `.is_(False)` (idioma SQLAlchemy corretto — il fix suggerito da ruff, `not ...`, avrebbe avuto un
  significato diverso su un'espressione di query)
- `ruff.toml`: `legacy/` escluso dal lint invece di essere corretto — non fa parte del codice
  attivamente mantenuto (vedi `CLAUDE.md` "Legacy code")

### Changed
- `.github/workflows/ci.yml`: rimosso `continue-on-error: true` dal job `lint` — ora blocca la CI come
  `pytest`, chiudendo lo Step 8 della roadmap

## 1.7.0 (2026-09-11)

### Changed
- **Iscrizione torneo disaccoppiata dall'invio del mazzo**: `/iscriviti` non apre più un modal di
  validazione deck — registra soltanto (`TournamentPlayer.deck_name` resta `None`). Il mazzo si invia (o
  reinvia, per correggere errori) separatamente con il nuovo `/invia_deck`, ripetibile finché il torneo
  resta in fase di registrazione. `services/tournament_service.py`: nuovo metodo `submit_deck()` che
  aggiorna un'iscrizione esistente (non ne crea una nuova, a differenza di `register_player()`)
- `start_tournament()` ora **rifiuta l'avvio** se un iscritto attivo (non droppato) non ha ancora inviato
  un mazzo valido, elencando chi manca — nessuna migrazione DB: riusa `deck_name is not None` come
  segnale "mazzo inviato"

### Added
- `/invia_deck [torneo_id]`: apre il modal di validazione deck (stesso flusso di prima, spostato qui) e
  aggiorna l'iscrizione esistente invece di crearne una
- `/iscrizioni_torneo [torneo_id]`: elenco iscritti con stato mazzo (✅ inviato / ⏳ in attesa), utile
  prima di avviare
- Log Discord: `PLAYER_UNREGISTERED` (uscita volontaria, `/left_torneo` — prima non loggata),
  `TOURNAMENT_START_BLOCKED` (WARN, quando `/avvia_torneo` viene rifiutato per qualunque motivo: torneo
  non trovato/non in registrazione, meno di 2 giocatori, o mazzi mancanti), `TOURNAMENT_DECK_SUBMITTED`
  (sostituisce `TOURNAMENT_DECK_CHECK` per il flusso torneo — vedi sotto)
- `TOURNAMENT_STARTED` ora include l'elenco completo dei partecipanti e il nome del mazzo di ciascuno
  (prima solo il messaggio di riepilogo)
- 5 nuovi test in `tests/tournament/test_tournament_service.py`: invio mazzo su iscrizione esistente,
  reinvio che sovrascrive, invio senza iscrizione (rifiutato), invio dopo l'avvio (rifiutato), avvio
  bloccato se manca un mazzo

### Fixed
- `TOURNAMENT_DECK_CHECK` era usato per due flussi diversi (check standalone `/artisan_check_deck` e,
  prima di questo cambio, la registrazione al torneo), rendendo ambiguo il canale log. Con la
  registrazione disaccoppiata, l'evento torna ad avere un solo significato; il flusso di invio mazzo
  torneo usa ora `TOURNAMENT_DECK_SUBMITTED`, distinto e filtrabile separatamente

## 1.6.1 (2026-09-11)

### Fixed
- Banlist e carte double-faced (`cogs/deck_validation/service.py`): `cards.txt`/`banned_cards` salva le
  double-faced col nome completo (`A-Blessed Hippogriff // A-Tyr's Blessing`), ma `parse_decklist()`
  tronca **sempre** al fronte quando legge il deck dell'utente (mimando il formato di export di MTG
  Arena) — non solo in un caso limite: il confronto in `check_banlist()` falliva sistematicamente per
  queste carte, che restavano bandite solo sulla carta ma non venivano mai effettivamente catturate.
  Nuova funzione `_expand_double_faced()` in `ArtisanService._load_banlist()`: aggiunge la sola metà
  fronte al set usato per il check, applicata solo alla cache di validazione — `/banlist` (comando
  pubblico) e `BanlistRepository.get_all_for_format()` continuano a mostrare solo le carte davvero
  salvate nel DB, non varianti sintetiche derivate

## 1.6.0 (2026-09-11)

### Changed
- Cache carte Scryfall (`utils/card_cache.py`): migrata da `data/card_cache.json` (riscritto per intero
  ogni 60s anche per una sola carta modificata) a una tabella SQLite (`cached_cards`,
  `database/models.py:CachedCard`) con scritture incrementali — `save_cache()` traccia i nomi carta
  modificati/rimossi (`_dirty_upserts`/`_dirty_deletes`) e fa UPSERT/DELETE mirati invece di un dump
  completo. `load_cache()` è ora `async` e chiamata una volta da `database/engine.py:init_db()` invece
  che da ogni `ArtisanService.__init__()`. Le funzioni sul percorso caldo
  (`get_cached_card`/`set_cached_card`) restano sincrone e operano sul dict in memoria come prima — nessun
  cambiamento al codice di validazione deck oltre alla rimozione della chiamata a `load_cache()`
  dall'`__init__`
- Se la tabella `cached_cards` è vuota e `data/card_cache.json` esiste ancora, viene migrato
  automaticamente una tantum al primo avvio dopo l'aggiornamento
- `data/card_cache.json` non è più tracciato in git (`git rm --cached`, aggiunto a `.gitignore`): 2.2MB
  già cresciuti per 8 commit senza alcun valore come storico versionato. Resta sul disco locale come file
  inerte (non più letto né scritto dal bot una volta popolata la tabella)

### Added
- `tests/deck_validation/test_card_cache.py`: 8 test diretti su `utils/card_cache.py` (caricamento,
  migrazione legacy, upsert/delete incrementali, no-op senza modifiche, reload dopo "riavvio" simulato).
  Suite totale: 93 → 101 test

## 1.5.1 (2026-09-11)

### Added
- `tests/deck_validation/test_artisan_service.py`: 5 test per `ArtisanService.validate_deck()` — deck
  bannato (nessuna chiamata Scryfall), deck valido, carta rara illegale, e due regressioni mirate: banlist
  invalidata su un'istanza deve essere visibile dall'altra (bug del Step 1), entry di cache legacy senza
  timestamp deve essere ri-verificata invece di considerata valida per sempre (Step 3). Nessuna chiamata
  di rete reale — `_post_with_retry`/`_get_with_retry` sostituiti per-istanza con funzioni finte. Suite
  totale: 93 test (88 → 93)

## 1.5.0 (2026-09-11)

### Added
- TTL di 30 giorni sul flag `artisan_legal` in cache (`utils/card_cache.py`): `mark_artisan_legal()`
  salva anche un timestamp (`artisan_legal_checked_at`); `is_artisan_legal_stale()` lo considera scaduto
  oltre il TTL o se il timestamp manca (entry cacheate prima di questa modifica). Una carta con flag
  scaduto viene ri-verificata via Scryfall invece di fidarsi ciecamente della cache — copre il caso di
  una carta la cui legalità Artisan cambia dopo una nuova stampa su Arena
- `/invalidate_card_cache <carta>` (admin): rimuove una carta dalla cache Scryfall, forzando un
  ricontrollo completo (dati + legalità Artisan) alla prossima validazione, senza aspettare il TTL

## 1.4.3 (2026-09-11)

### Refactored
- `services/tournament_service.py`: unificata la gestione delle sessioni DB. I ~20 metodi ripetevano
  ciascuno `session, repo... = self._get_repos()` seguito da `try/finally: await session.close()`. Ora
  `self._repos()` è un context manager asincrono (`@asynccontextmanager`) che apre sessione e repository
  e li chiude sempre all'uscita del blocco (`async with self._repos() as (session, trepo, tprepo, mrepo,
  urepo):`). Nessuna logica di business toccata — refactor puramente meccanico, un `async with` al posto
  di ogni `try/finally`

## 1.4.2 (2026-09-11)

### Changed
- `services/tournament_service.py`: `_update_ratings()` caricava ogni `User` con un `session.get()`
  separato dentro un ciclo sui giocatori del torneo (query N+1). Sostituito con un'unica query batch
  (`select(User).where(User.id.in_(user_ids))`) — impatto oggi trascurabile con tornei da poche decine di
  giocatori, ma non scalava

## 1.4.1 (2026-09-11)

### Fixed
- `database/engine.py`: `_migrate_schema()` avvolgeva ogni `ALTER TABLE` in un `try/except Exception:
  pass` generico — pensato per il caso "colonna già esistente", ma capace di nascondere silenziosamente
  anche errori reali (permessi, disco pieno, tipo colonna incompatibile). Ora verifica esplicitamente
  l'esistenza della colonna via `PRAGMA table_info(<tabella>)` prima di ogni `ALTER TABLE`; un fallimento
  imprevisto viene stampato su stdout (`ERRORE migrazione: ...`) invece di sparire senza traccia. Le 8
  migrazioni sono ora dichiarate come lista di tuple `(tabella, colonna, ddl)` invece di 8 blocchi
  try/except ripetuti — aggiungerne una nuova non richiede più toccare la funzione
- Rimosso `import os` duplicato in cima a `database/engine.py`

### Docs
- `docs/database.md`, `CLAUDE.md`: aggiornati per descrivere il nuovo controllo esplicito delle
  migrazioni invece del pattern try/except generico

## 1.4.0 (2026-09-11)

### Fixed
- Cache banlist (`ArtisanService`): il fix del 9 settembre (`reload_banlist()`) restava incompleto — il
  bot istanzia due `ArtisanService` separate (`tournament_system` e `deck_validation`), e ricaricare
  `self._banlist` su una non aveva effetto sull'altra. La cache è ora condivisa a livello di modulo
  (`_banlist_cache` in `cogs/deck_validation/service.py`, stesso pattern di `utils/arena_overrides.py`),
  cosi' un'invalidazione da un comando è visibile immediatamente da entrambe le istanze

### Docs
- `docs/ClepshydraBot_Resoconto_Tecnico.md`: ridotto a scheda infra/specifiche/stack — rimossa la
  duplicazione con `docs/infrastruttura.md` e con gli altri doc dedicati (architettura, cache,
  validazione mazzi, banlist); sostituite le sezioni rimosse con una tabella di rimandi
- Aggiunto `docs/roadmap-miglioramenti.md`: piano di lavoro per debito tecnico e miglioramenti
  architetturali residui, con un riepilogo di cosa era già stato affrontato nell'intervento del 9
  settembre (CI, test `TournamentService`, resilienza avvio)
- `docs/infrastruttura.md`: corretta la sezione Deployment — il processo in produzione è gestito con
  `pm2` (restart automatico su crash), non `screen`/`tmux` come indicato in precedenza; `systemd`
  (`deploy/clepshydrabot.service`) riclassificato come alternativa disponibile ma non in uso
- `docs/banlist-system.md`, `docs/caching.md`: aggiornati per riflettere la cache banlist condivisa a
  livello di modulo invece che per istanza
- Aggiunto `CLAUDE.md` (guida per Claude Code): comandi di sviluppo/test, architettura a layer, pipeline
  di validazione deck, lifecycle torneo — unito con la sezione "Agent skills" già presente

## 1.3.2 (2026-09-09)

### Added
- `.github/workflows/ci.yml`: `pytest` come gate bloccante su ogni push/PR; `ruff` come step
  informativo/non bloccante (debito di lint pre-esistente non ancora sanato)
- `tests/tournament/test_tournament_service.py`: 10 test end-to-end sull'orchestratore torneo
  (iscrizione, avvio, pairing, submit risultato, round successivo con anti-rematch, conclusione + rating
  update, drop forzato, standings) contro un DB SQLite isolato per test, senza mock — suite totale: 88
  test verdi
- `deploy/clepshydrabot.service`: unit systemd (`Restart=on-failure`) come opzione di process management
  alternativa, raccomandata nei doc ma non ancora resa disponibile come file

### Fixed
- `main.py`: `discord.LoginFailure` e altre eccezioni di startup ora vengono intercettate con log
  esplicito su stderr (prefisso `FATAL:`) ed exit code non-zero, invece di fallire in modo silenzioso o
  con una traceback ambigua
- `pytest.ini` (`pythonpath = .`): `pytest tests/ -v` (invocazione nuda, usata dalla CI) falliva con
  `ModuleNotFoundError` sui moduli di primo livello — a differenza di `python -m pytest`, non aggiunge
  automaticamente la root del repo a `sys.path`
- `tests/tournament/conftest.py`: variabili d'ambiente di test spostate qui per garantire l'ordine
  corretto di collection (`services/__init__.py` importa eagerly `TournamentService`, che richiede
  `config.config` popolato)
- Cache banlist (`ArtisanService`): primo fix — `reload_banlist()` invalida la cache dopo
  `/banlist_aggiungi`/`/banlist_rimuovi` invece di aspettare un riavvio del bot (completato l'11
  settembre, vedi 1.4.0 sopra)

## 1.3.1 (2026-07-05)

### Added
- 28 new unit tests for `PairingEngine` and Glicko-2 rating system (48 → 76 total)
- Test coverage for: pairing round generation, anti-rematch, bye dedup, scoreboard, rating properties, Glicko-2 scaling

### Fixed
- `normalizza_gilda` in `presentation/validators.py`: duplicate key `"gu"` silently overwrote Simic → Gruul (now `"gu"` correctly maps to Simic)
- `interaction_check` in `presentation/views.py`: publish logic moved from hook to dedicated `_on_confirm` callback

### Changed
- `config/config.py`: `TOURNAMENT_CHANNEL_ID`, `PUBLIC_DECK_CHANNEL_ID` now support `_TEST` env vars like other channels

### Refactored
- `cogs/tournament/` → `cogs/deck_validation/`: renamed to disambiguate from `cogs/tournament_system/`; all imports and docs updated
- `PRESENTATION_DATA_STORE` moved from `modals.py` to `models.py` (neutral data module)
- Circular dependency `views` ↔ `modals` broken: modals now accept `on_complete` callbacks instead of importing view classes
- All 7 lazy imports in `cogs/presentation/` moved to top-level — no more runtime import resolution
- `PreviewView.interaction_check` reduced to single responsibility (guard check only)

### Docs
- `docs/banlist-system.md`, `docs/comandi.md`, `docs/deck-validation.md`: updated module paths for rename

## 1.3.0 (2026-07-05)

### Added
- Complete documentation suite in `docs/`: architettura, presentazioni, tornei, deck-validation, database, infrastruttura, comandi, caching, resoconto tecnico
- Paginated `/banlist` command with embed fields (30 cards per field)
- `/banlist_aggiungi` and `/banlist_rimuovi` commands for admin banlist management
- `BanlistRepository` with SQLite-backed CRUD operations
- Banlist seed migration from `cards.txt` to `banned_cards` table on first startup
- Schema migration system for incremental column additions (`deck_name`, `p1/p2_game_wins`, rating fields)
- Test suite for tournament standings, embeds, and logic utilities

### Fixed
- HBG (Hearthstone Battlegrounds) non-Alchemy cards incorrectly marked as illegal in Artisan format
- Deck image generation skipping cards due to corrupted cache entries
- Presentation channel lookup failing after bot restart
- Message deletion timing in presentation flow
- BYE assigning duplicate byes to same player across brackets
- Game win percentage calculation: now computed on real games only (excludes BYE)
- Match win percentage: BYE correctly counted as 2-0 for MWP calculation
- Player1/Player2 game wins mapping to correct player slots in match submission

## 1.2.0 (2026-07-03)

### Added
- Glicko-2 rating system: `rate_1vs1()` with game score consideration, `rate_draw()`
- `TournamentService._update_ratings()` — batch rating update on tournament completion
- `/leaderboard [limite]` command displaying `rating - 2*RD` lower bound
- `/lista_tornei` command listing all tournaments with status and player count
- Official tiebreaker system: OMW (floor 33%), GWP (floor 33%), OGW in `StandingsCalculator`
- Swiss bracket pairing with OMW% sorting within score brackets in `PairingEngine`
- `MatPlotLib`-style OMW progress bar in standings embeds

### Changed
- Standings embed: added medal labels, rank formatting, OMW bar visualization
- Pairing embed: player mention links, table numbers, round header
- Tournament completion flow: automatic rating update before status change

## 1.1.0 (2026-06-30)

### Added
- Full tournament system with `/iscriviti`, `/left_torneo`, `/risultato`, `/classifica`, `/turni`
- `TournamentService` orchestrator with complete tournament lifecycle
- Deck validation on registration via `ArtisanService.validate_deck()`
- `PairingEngine` with round 1 shuffle, Swiss bracket pairing, anti-rematch, BYE handling
- `StandingsCalculator` with 3/1/0 scoring
- `IscrivitiModal` with deck text input + automatic validation
- `RisultatoView` with interactive game win selection (0-2)
- Deck showcase publishing to tournament channel on registration

### Fixed
- Player drop during registration phase now correctly removes from tournament
- Duplicate registration prevention (existing player check)
- Edge case: tournament with 0 players cannot be started

## 1.0.0 (2026-06-27)

### Added
- Swiss tournament system: `/crea_torneo`, `/avvia_torneo`, `/torneo_next_turn`, `/drop_giocatore`, `/concludi_torneo`
- SQLite database via SQLAlchemy 2.0 async
- Repository layer (UserRepository, TournamentRepository, MatchRepository, TournamentPlayerRepository)
- PairingEngine with basic Swiss algorithm, anti-rematch, bye handling
- StandingsCalculator with 3/1/0 scoring and opponent win % tiebreaker
- Full project structure for V2 architecture (services, repositories, database)

### Refactored
- Tournament deck check: split 495-line monolithic cog into models, validators, embeds, service
- Presentation system: multi-step wizard with select menus and preview
- Config centralized in `config/config.py` with `TEST_MODE` support

### Changed
- Updated `.env.example` with all required environment variables
- Updated `.gitignore` for SQLite database files
- README updated to reflect V2 architecture

## 0.1.0 (2026-06-26)

### Added
- Initial bot setup with discord.py
- User presentation system with role assignment
- Artisan deck validation via Scryfall API
- Deck image generation with Pillow
- SPG rarity override system
- Centralized logging to Discord channel
- Card caching with periodic JSON persistence
- Presentation: Deck, Sideboard, About parsing
- Basic banlist support from cards.txt
- Background image selection by color identity
