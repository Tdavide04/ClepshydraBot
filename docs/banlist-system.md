# Card Banlist System — Clepshydra Bot

## Overview

The system manages the cards banned in the **Artisan** format (only Common and Uncommon cards on MTG Arena).
The banlist lists cards that, although common or uncommon, are banned because they are considered too strong
for the format.

**Note**: `features/monitors/ban_announcement.py` watches Wizards' official "Banned and Restricted Announcement" posts
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
│    → imports seeds/banlist.txt into the SQLite DB       │
│    → only if the table is empty                         │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│             BanlistRepository                           │
│  features/deck_validation/banlist_repository.py         │
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

### 1. Seed Data — `seeds/banlist.txt`

Text file with the starting banlist, one card per line (it was `cards.txt` at the repository root until
4.0.2). It is read only to fill an empty `banned_cards` table, so it matters only on a fresh database:
**the banlist in the DB is authoritative**, and staff change it with `/banlist_aggiungi` and
`/banlist_rimuovi`. The seed is never updated by those commands, so it can be older than the real banlist.
It sits in `seeds/`, apart from `data/`, which holds only runtime state ignored by git.
It includes:
- Cards with the `A-` prefix (Alchemy versions on Arena)
- Double-faced cards (`Name // Name`)
- "Normal" banned cards (e.g. `Abiding Grace`, `Mishra's Bauble`)

### 2. Startup Migration — `_migrate_banlist()` in `database/engine.py`

At startup, `_migrate_banlist()`:
1. Checks whether `seeds/banlist.txt` exists
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

### 4. Repository — `features/deck_validation/banlist_repository.py`

| Method | Role |
|---|---|
| `get_all_for_format(format="Artisan")` | Returns a `set[str]` with every (lowercase) banned card name for the format |
| `add_card(card_name, format="Artisan")` | Adds a card to the banlist |
| `contains(card_name)` | Whether the card is banned, case-insensitive |
| `remove_card(card_name)` | Removes a card, case-insensitive, returns `True/False` |
| `count()` | Total number of banned cards |
| `import_from_file(path)` | Bulk import from a text file (only if the table is empty) |

### 5. Deck Validation — `ArtisanService.validate_deck()` in `features/deck_validation/service.py`

`ArtisanService.validate_deck()`:
1. On the first call, loads the banlist into the module cache `_banlist_cache` via `_load_banlist()` →
   `BanlistRepository.get_all_for_format()`, then expands double-faced cards with `_expand_double_faced()`
   (adds the front half alone next to the full name — see "Known Issues" item 1)
2. Calls `check_banlist(entries, _banlist_cache)` (from `features/deck_validation/validators.py`)
3. If it finds banned cards, returns `DeckValidationResult(banned_cards=[...])` right away → deck **invalid**
4. If no card is banned, goes on with the rarity validation (Scryfall API)

### 6. Banlist Check — `check_banlist()` in `features/deck_validation/validators.py`

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

### 7. Slash Commands — `banlist_lista`/`banlist_aggiungi`/`banlist_rimuovi` in `features/deck_validation/cog.py`

Next to `/artisan_check_deck`, in `DeckValidationCog`, since 4.0.0; until then they lived in the tournament cog
and only worked in `TOURNAMENT_CHANNEL_ID`. They now work in any channel.

| Command | Description | Permissions |
|---|---|---|
| `/banlist` | Shows every banned card in a paginated embed (30 per field) | Public |
| `/banlist_aggiungi <carta>` | Adds a card to the DB; refuses a blank name and a card already banned (any case) | `@is_admin()` (`Staff` role) |
| `/banlist_rimuovi <carta>` | Removes a card from the DB, matching the name in any case | `@is_admin()` |

The cog only builds the embed and logs `BANLIST_ADD`/`BANLIST_REMOVE` on success. The work is in
`BanlistService` (`features/deck_validation/banlist_service.py`, since 4.0.4): `list_cards()` returns the
sorted names (`None` when the DB isn't initialized), `add_card()` and `remove_card()` return a
`ServiceResult` whose `message` the cog sends as is. Before 4.0.4 the cog opened DB sessions itself, a
duplicate raised `IntegrityError` (`card_name` is `UNIQUE`) and reached staff as the generic error, and
removal matched the stored name exactly, so removing a card as `/banlist` shows it (lowercased) failed.

### 8. Result Embed — `features/deck_validation/embeds.py`

If the deck has banned cards, the embed shows:
- **Carte Bannate**: the list (max 10)
- **Resoconto** (summary): count of banned cards
- Red color (`is_valid = False`)

### 9. Caching

The banlist is cached in memory in the module variable `_banlist_cache: set[str] | None` in
`features/deck_validation/service.py`, shared by every `ArtisanService` instance. It is loaded from the DB on the
first validation (or after an invalidation) and kept in memory until invalidated.

`BanlistService` calls `invalidate_banlist_cache()` after every successful add or remove, and the next
validation reloads the banlist from the DB. Since the cache is shared at module level (instead of a
per-instance attribute), the invalidation is immediately visible to **both** `ArtisanService` instances the
bot creates (`features/tournaments/cog.py`, when that cog is loaded, and `features/deck_validation/cog.py`).

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
- The local file `seeds/banlist.txt` for the initial seed
- The SQLite database for persistent storage
- A purely textual comparison (`name.lower() in banlist`)

The Scryfall APIs are used in the next phase (Artisan rarity validation), not for the banlist. That phase —
SPG rarity overrides (`features/deck_validation/arena_overrides.py`, `data/arena_rarity_data.json`, seeded from
`seeds/arena_rarity.json`), the Scryfall card cache
(`features/deck_validation/card_cache.py`, `cached_cards` table, TTL on `artisan_legal`) and the Arena legality check — is
documented in `docs/deck-validation.md` (flow) and `docs/caching.md` (caches and overrides).

---

## Known Issues

1. **Double-faced cards** — fixed. The seed and `banned_cards` store the full name
   (`A-Blessed Hippogriff // A-Tyr's Blessing`), but `parse_decklist()` always truncates to the front face
   when reading the user's deck (mimicking MTG Arena's export format), so the comparison **always** failed
   for these cards. `ArtisanService._load_banlist()` (`features/deck_validation/service.py`) now expands the
   banlist with `_expand_double_faced()` — for every entry containing ` // `, it also adds the front half
   alone to the set used by `check_banlist()`. Applied **only** to the validation cache, not to
   `BanlistRepository.get_all_for_format()`: that method also feeds `/banlist` (a public command), which
   must list only the cards actually stored in the DB, not synthetic variants.

2. **Live updates** — fixed. `self._banlist` in `ArtisanService` wasn't invalidated after add/remove via
   slash command. `/banlist_aggiungi` and `/banlist_rimuovi` now invalidate it after writing to the DB
   (`BanlistService`, since 4.0.4; `ArtisanService.reload_banlist()` before). The cache is module-level
   (`_banlist_cache`), so the invalidation also covers the second `ArtisanService` instance used by
   `features/deck_validation/cog.py` — a first attempt with a per-instance cache would have left that second
   instance stale.

3. **Case sensitivity**: everything is lowercased, so there is no issue.
