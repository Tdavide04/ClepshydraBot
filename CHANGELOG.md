# Changelog

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
