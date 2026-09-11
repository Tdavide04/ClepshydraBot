# Changelog

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
