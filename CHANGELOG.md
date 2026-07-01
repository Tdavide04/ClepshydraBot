# Changelog

## 1.0.0 (2026-06-27)

### Added
- Swiss tournament system: `/torneo`, `/iscriviti`, `/risultato`, `/classifica`, `/turni`
- SQLite database via SQLAlchemy 2.0 async
- Repository layer (UserRepository, TournamentRepository, MatchRepository)
- PairingEngine with Swiss algorithm, anti-rematch, bye handling
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
