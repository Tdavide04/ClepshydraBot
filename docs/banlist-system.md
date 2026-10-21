# Card Banlist System — Clepshydra Bot

## Overview

The system manages the cards banned in the **Artisan** format (only Common and Uncommon cards on MTG Arena).
The banlist lists cards that, although common or uncommon, are banned because they are considered too strong
for the format.

**Note**: `utils/ban_announcement.py` watches Wizards' official "Banned and Restricted Announcement" posts
and notifies when a new one comes out (see `docs/caching.md` section 3b), but it is **only a reminder** — it
never writes to `banned_cards`. None of the official formats those announcements cover (Standard, Modern,
Alchemy, etc.) is this community's homebrew Artisan, so updating the banlist always stays manual via
`/banlist_aggiungi`/`/banlist_rimuovi`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Bot startup                          │
│  database/engine.py:_migrate_banlist()                  │
│    → imports cards.txt into the SQLite DB               │
│    → only if the table is empty                         │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│             BanlistRepository                           │
│  repositories/banlist_repository.py                     │
│  • CRUD on the banned_cards table                       │
│  • get_all_for_format() → set[str]                     │
│  • add_card() / remove_card()                           │
│  • import_from_file()                                   │
└──────────────────────┬──────────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌──────────────────┐    ┌──────────────────────────────┐
│  Deck validation │    │  Slash commands               │
│  (ArtisanService)│    │  /banlist (public)            │
│                  │    │  /banlist_aggiungi (admin)    │
│                  │    │  /banlist_rimuovi (admin)     │
└──────────────────┘    └──────────────────────────────┘
```

---

## Components in Detail

### 1. Seed Data — `cards.txt`

Text file with 219 banned cards, one per line. It includes:
- Cards with the `A-` prefix (Alchemy versions on Arena)
- Double-faced cards (`Name // Name`)
- "Normal" banned cards (e.g. `Abiding Grace`, `Mishra's Bauble`)

### 2. Startup Migration — `_migrate_banlist()` in `database/engine.py`

At startup, `_migrate_banlist()`:
1. Checks whether `cards.txt` exists
2. Calls `BanlistRepository.import_from_file()`
3. If the table is empty, imports every card with format=`"Artisan"`
4. If the table already has data, skips the import (no duplicates)

### 3. Data Model — `BannedCard` in `database/models.py`

```python
class BannedCard(Base):
    __tablename__ = "banned_cards"

    id          = Column(Integer, primary_key=True)
    card_name   = Column(String(200), unique=True, index=True)  # exact name
    format      = Column(String(50), default="Artisan")         # format it belongs to
    created_at  = Column(DateTime, default=datetime.now)
```

### 4. Repository — `repositories/banlist_repository.py`

| Method | Role |
|---|---|
| `get_all_for_format(format="Artisan")` | Returns a `set[str]` with every (lowercase) banned card name for the format |
| `add_card(card_name, format="Artisan")` | Adds a card to the banlist |
| `remove_card(card_name)` | Removes a card by exact name, returns `True/False` |
| `count()` | Total number of banned cards |
| `import_from_file(path)` | Bulk import from a text file (only if the table is empty) |

### 5. Deck Validation — `ArtisanService.validate_deck()` in `cogs/deck_validation/service.py`

`ArtisanService.validate_deck()`:
1. On the first call, loads the banlist into the module cache `_banlist_cache` via `_load_banlist()` →
   `BanlistRepository.get_all_for_format()`, then expands double-faced cards with `_expand_double_faced()`
   (adds the front half alone next to the full name — see "Known Issues" item 1)
2. Calls `check_banlist(entries, _banlist_cache)` (from `cogs/deck_validation/validators.py`)
3. If it finds banned cards, returns `DeckValidationResult(banned_cards=[...])` right away → deck **invalid**
4. If no card is banned, goes on with the rarity validation (Scryfall API)

### 6. Banlist Check — `check_banlist()` in `cogs/deck_validation/validators.py`

```python
def check_banlist(entries: list[DeckEntry], banlist: set[str]) -> list[str]:
    banned: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.name.lower() in banlist and entry.name not in seen:
            banned.append(entry.name)
            seen.add(entry.name)
    return banned
```

Logic:
- Iterates over every card in the deck
- Compares the (lowercase) name with the banlist
- On a match, adds it to the result list (no duplicates)
- If the resulting list isn't empty → deck invalid

### 7. Banlist from File (legacy) — `load_banlist()` in `cogs/deck_validation/validators.py`

`load_banlist()` is no longer called by any code:
- Reads `cards.txt` line by line
- For double-faced cards (` // `), also adds the front name alone
- Returns a `set[str]` (lowercase)

### 8. Slash Commands — `banlist_lista`/`banlist_aggiungi`/`banlist_rimuovi` in `cogs/deck_validation/__init__.py`

Next to `/artisan_check_deck`, in `DeckValidationCog`, since 3.7.0; until then they lived in the tournament cog
and only worked in `TOURNAMENT_CHANNEL_ID`. They now work in any channel.

| Command | Description | Permissions |
|---|---|---|
| `/banlist` | Shows every banned card in a paginated embed (30 per field) | Public |
| `/banlist_aggiungi <carta>` | Adds a card to the DB | `@is_admin()` (`Staff` role) |
| `/banlist_rimuovi <carta>` | Removes a card from the DB | `@is_admin()` |

### 9. Result Embed — `cogs/deck_validation/embeds.py`

If the deck has banned cards, the embed shows:
- **Carte Bannate**: the list (max 10)
- **Resoconto** (summary): count of banned cards
- Red color (`is_valid = False`)

### 10. Caching

The banlist is cached in memory in the module variable `_banlist_cache: set[str] | None` in
`cogs/deck_validation/service.py`, shared by every `ArtisanService` instance. It is loaded from the DB on the
first validation (or after an invalidation) and kept in memory until invalidated.

`ArtisanService.reload_banlist()` forces the refresh: `/banlist_aggiungi` and `/banlist_rimuovi` call it right
after writing to the DB. Since the cache is shared at module level (instead of a per-instance attribute), the
invalidation is immediately visible to **both** `ArtisanService` instances the bot creates
(`tournament_system/cog.py`, when that cog is loaded, and `cogs/deck_validation/__init__.py`) — not only the one the method is called
on.

---

## Full Flow (Deck Check with Banlist)

```
User submits a deck
    → /invia_deck (tournament) or /artisan_check_deck
        → ArtisanService.validate_deck()
            → _load_banlist()  (if not in memory yet)
                → BanlistRepository.get_all_for_format()
                    → SELECT card_name FROM banned_cards WHERE format = 'Artisan'
            → check_banlist(entries, banlist)
                → [name1, name2, ...]  or []
            ↓
    ┌───────┴───────┐
    │ banned != []   │  banned == []
    │                │
    ▼                ▼
Deck INVALID     Deck OK
(banned found)   → goes on with
                   rarity validation
                   (Scryfall API)
```

---

## External APIs

The banlist system **calls no external API**. It only uses:
- The local file `cards.txt` for the initial seed
- The SQLite database for persistent storage
- A purely textual comparison (`name.lower() in banlist`)

The Scryfall APIs are used in the next phase (Artisan rarity validation), not for the banlist. That phase —
SPG rarity overrides (`utils/arena_overrides.py`, `data/arena_rarity_data.json`), the Scryfall card cache
(`utils/card_cache.py`, `cached_cards` table, TTL on `artisan_legal`) and the Arena legality check — is
documented in `docs/deck-validation.md` (flow) and `docs/caching.md` (caches and overrides).

---

## Known Issues

1. **Double-faced cards** — fixed. `cards.txt`/`banned_cards` store the full name
   (`A-Blessed Hippogriff // A-Tyr's Blessing`), but `parse_decklist()` always truncates to the front face
   when reading the user's deck (mimicking MTG Arena's export format), so the comparison **always** failed
   for these cards. `ArtisanService._load_banlist()` (`cogs/deck_validation/service.py`) now expands the
   banlist with `_expand_double_faced()` — for every entry containing ` // `, it also adds the front half
   alone to the set used by `check_banlist()`. Applied **only** to the validation cache, not to
   `BanlistRepository.get_all_for_format()`: that method also feeds `/banlist` (a public command), which
   must list only the cards actually stored in the DB, not synthetic variants.

2. **Live updates** — fixed. `self._banlist` in `ArtisanService` wasn't invalidated after add/remove via
   slash command. `/banlist_aggiungi` and `/banlist_rimuovi` now call `ArtisanService.reload_banlist()` right
   after writing to the DB (see `cogs/deck_validation/__init__.py`). The cache is module-level
   (`_banlist_cache`), so the invalidation also covers the second `ArtisanService` instance used by
   `cogs/deck_validation/__init__.py` — a first attempt with a per-instance cache would have left that second
   instance stale.

3. **Case sensitivity**: everything is lowercased, so there is no issue.
