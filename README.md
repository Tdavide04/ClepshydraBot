# ClepshydraBot

A Discord bot developed for the **Clepshydra** Magic: The Gathering Arena community.

The project aims to automate community management, simplify tournament organization, and provide useful tools for both players and staff members.

> **Current Version:** V1 (Legacy Architecture)
>
> A major architectural refactor (V2) is currently in development.

---

## Features

### User Presentation System

- `/presentati` slash command
- Interactive modal-based presentation
- Automatic role assignment
- Presentation logging
- Custom embed generation

### Artisan Deck Validation

- Validate deck legality for the Artisan format
- Integration with the Scryfall API
- Automatic rarity verification
- Override system for Arena-exclusive cards
- Cached card data for improved performance

### Tournament Utilities

- Deck submission
- Deck image generation
- Automatic validation before submission
- Tournament channel integration

### Logging

- Centralized logging system
- Staff notifications
- Error reporting
- Administrative actions tracking

---

## Tech Stack

- Python 3
- discord.py
- aiohttp
- Pillow
- JSON persistence
- Scryfall API

---

## Project Structure

```
ClepshydraBot/

├── assets/
├── cogs/
│   ├── logger.py
│   ├── presentation.py
│   ├── spg_override_updater.py
│   └── tournament.py
│
├── data/
│   ├── arena_rarity_data.json
│   └── card_cache.json
│
├── legacy/
│   ├── legacy_bot.py
│   └── README.md
│
├── utils/
│   ├── arena_overrides.py
│   ├── card_cache.py
│   └── deck_image_generator.py
│
├── main.py
├── requirements.txt
└── .env.example
```

---

## Installation

Clone the repository:

```bash
git clone https://github.com/your_username/ClepshydraBot.git
cd ClepshydraBot
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file based on `.env.example`.

Run the bot:

```bash
python main.py
```

---

## Environment Variables

Example:

```env
TOKEN=
GUILD_ID=
LOG_GUILD_ID=
PUBLIC_DECK_CHANNEL_ID=
```

---

## Current Architecture (V1)

The current version follows a Cog-based architecture where most of the business logic resides inside Discord Cogs.

While fully functional, this version has some known limitations:

- Large Cog files
- Business logic mixed with Discord UI
- JSON-based persistence
- Limited modularity
- Minimal automated testing

These issues will be addressed in Version 2.

---

## Roadmap

### Version 2

Planned improvements:

- Layered architecture
- Service layer
- Repository pattern
- SQLite + SQLAlchemy
- Tournament engine
- Multi-step presentation wizard
- Docker support
- GitHub Actions
- Automated testing
- Improved documentation

---

## Legacy

The `legacy/` directory contains the very first implementation of ClepshydraBot.

It is preserved for historical purposes only and is no longer maintained.

---

## License

This project is currently distributed for educational and personal use.

A license will be added once the V2 architecture is completed.

---

## Author

Developed by **Davide Trischitta**

Project created for the Clepshydra Discord community.