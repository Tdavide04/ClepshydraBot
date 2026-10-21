# Artisan Deck Validation

## Overview

The validation system checks that decks follow the rules of the **Artisan** format (only Common and Uncommon
cards on MTG Arena). It combines a local banlist, the Scryfall API, SPG rarity overrides and caching.

---

## Structure

```
features/deck_validation/
├── cog.py                # ArtisanDeckCheckModal + DeckValidationCog (/artisan_check_deck, banlist commands)
├── spg_cog.py            # SPGOverrideUpdater (/forced_rarity_refresh, /invalidate_card_cache)
├── models.py             # DeckEntry, ArtisanCard, DeckValidationResult
├── validators.py         # parse_decklist(), check_banlist(), validate_counts()
├── service.py            # ArtisanService.validate_deck()
├── embeds.py             # Embed builder for validation results
├── banlist_repository.py # BanlistRepository (banned_cards table)
├── card_cache.py         # Persistent Scryfall cache (SQLite)
├── arena_overrides.py    # SPG rarity overrides
└── image.py              # DeckImageGenerator: showcase image generation
```

---

## Validation Flow

```
                    DECK LIST (text pasted by the user)
                                │
                                ▼
                    ┌───────────────────────┐
                    │   parse_decklist()     │
                    │   • reads About block  │
                    │   • splits main/side   │
                    │   • strips set code    │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │    check_banlist()     │
                    │   • O(1) set lookup    │
                    └───────────┬───────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
            BANNED FOUND             NONE BANNED
                    │                       │
                    ▼                       ▼
            DECK INVALID            ┌───────────────────────┐
            (stop, no API)          │  _fetch_collection()   │
                                    │  • cache check         │
                                    │  • Scryfall batch API  │
                                    └───────────┬───────────┘
                                                │
                                                ▼
                                    ┌───────────────────────┐
                                    │ _is_arena_artisan_     │
                                    │ legal() for each card  │
                                    │ • SPG override check   │
                                    │ • Arena prints search  │
                                    └───────────┬───────────┘
                                                │
                                    ┌───────────┴───────────┐
                                    ▼                       ▼
                            ILLEGAL FOUND            ALL LEGAL
                                    │                       │
                                    ▼                       ▼
                            DECK INVALID            ┌───────────────────────┐
                                                    │ count validation      │
                                                    │ main >= 60, side<=15 │
                                                    └───────────┬───────────┘
                                                                │
                                                    ┌───────────┴───────────┐
                                                    ▼                       ▼
                                            COUNT ERROR             COUNT OK
                                                    │                       │
                                                    ▼                       ▼
                                            DECK INVALID            ┌───────────────────────┐
                                                                    │ generate deck image   │
                                                                    │ publish embed         │
                                                                    └───────────────────────┘
```

---

## Components

### 1. Decklist Parser (`parse_decklist()` in `validators.py`)

`parse_decklist(raw: str) -> tuple[list[DeckEntry], int, str]` — returns `(entries, total_cards, deck_name)`.

- Reads the deck name from an initial `About` block (default `"ARTISAN DECK"`)
- Skips the `Deck` header; everything after a `Sideboard` line is sideboard
- Parses lines like `3 Lightning Bolt (ONE) 123` → quantity, name; strips the set code and collector number
- Normalizes typographic quotes and keeps only the front face of `Front // Back` names (MTG Arena's export
  format)

### 2. Banlist Check (`check_banlist()` in `validators.py`)

`check_banlist(entries, banlist) -> list[str]`

- Case-insensitive comparison (`name.lower()`)
- O(1) lookup on a `set[str]`
- No duplicates in the result
- Non-empty list → deck invalid

The banlist set comes from `ArtisanService._load_banlist()` (DB + front halves of double-faced cards, see
`docs/banlist-system.md`). `load_banlist()`, a file-based version in the same module, is no longer used.

### 3. Scryfall Fetch (`_fetch_collection()` in `service.py`)

`async _fetch_collection(session, names)`

- Groups the cards not in cache
- Calls `POST /cards/collection` in chunks of 75
- Stores the results in the card cache (`set_cached_card()`, persisted to the `cached_cards` table)
- Rate limiting: semaphore with 1 request at a time, 110ms delay

### 4. Arena Legality Check (`_is_arena_artisan_legal()` in `service.py`)

`async _is_arena_artisan_legal(session, card_data, card_name) -> bool`

Order of the checks:
1. **Local override** → `get_override_rarity(card_name)` → if common/uncommon → legal
2. **Card cache** → the `artisan_legal` field of the cached entry, **only if not stale**
   (`is_artisan_legal_stale()`, 30-day TTL — see `docs/caching.md`); an entry without
   `artisan_legal_checked_at` (cached before the TTL existed) counts as stale
3. **Memory cache** → `oracle_id` already checked (`_ARENA_LEGAL_CACHE`, for the life of the process — no TTL)
4. **Scryfall API** → `GET prints_search_uri` with `game:arena` added to the query

In the API call:
- Skips `set_type=alchemy` printings (excluded from Artisan)
- Checks whether a common/uncommon printing exists on Arena
- Stores the result in cache with a timestamp (`mark_artisan_legal()`)

### Scryfall Unreachable

`_request_with_retry()` (used by `_post_with_retry`/`_get_with_retry`) tells apart two outcomes that until
3.5.6 both became `None`:

- **404** → `{"data": []}`: on `/cards/search` it means "no printings found", so the card has no Arena
  printings and is **illegal** — a valid outcome, cached as before
- **network error, timeout, 5xx or 429 past the 5 attempts, any other unexpected status** → raises
  `ScryfallUnavailable`. 5xx responses are now retried with backoff like timeouts (before: immediate give-up)

`validate_deck()` catches `ScryfallUnavailable` and returns a `DeckValidationResult` with `service_error`
set and no card in `invalid_cards`/`illegal_rarity_cards`: the deck **was not evaluated**, neither valid nor
invalid. No cache is touched. `/invia_deck` and `/artisan_check_deck` reply that Scryfall isn't answering
and to retry in a few minutes (the tournament registration stays unchanged) and log WARN
`SCRYFALL_UNAVAILABLE`.

Before 3.5.7 a single timeout on the printings search stored the card as illegal in `_ARENA_LEGAL_CACHE`
until the bot restarted (every deck containing it was refused as "Non legali in Artisan Arena"), and a
failed `/cards/collection` block made its cards show up under "Carte non trovate".

To force an immediate re-check of a single card (without waiting for the TTL), an admin can use
`/invalidate_card_cache <carta>`.

### 5. Counts

- Mainboard: at least 60 cards
- Sideboard: at most 15 cards

`DeckValidationResult.is_valid` applies these limits itself. `validate_counts(main_count, side_count)` in
`validators.py` returns the human-readable count errors, used by `/invia_deck` in the tournament cog.

### 6. Image Generation (`features/deck_validation/image.py`)

`DeckImageGenerator.create_deck_showcase(session, mainboard, sideboard, player_name=None, deck_name="ARTISAN DECK") -> BytesIO`

- Picks a guild/color background from `assets/backgrounds/`, based on the deck's colors
- Downloads the card images from Scryfall
- Compositing: header, mainboard grid by section, sideboard column
- Clepshydra logo watermark at the bottom, centered on the sideboard column, tinted with the background's
  dominant color

---

## Data Models (`models.py`)

```python
@dataclass
class DeckEntry:
    quantity: int
    name: str
    is_sideboard: bool

@dataclass
class ArtisanCard:
    name: str
    quantity: int
    image_url: str | None
    type_line: str
    cmc: float
    is_sideboard: bool

@dataclass
class DeckValidationResult:
    deck_name: str
    total_cards: int
    main_count: int
    side_count: int
    banned_cards: list[str]          # default []
    invalid_cards: list[str]         # shown as "Carte non trovate"
    illegal_rarity_cards: list[str]  # shown as "Non legali in Artisan Arena"
    mainboard: list[ArtisanCard]
    sideboard: list[ArtisanCard]
    service_error: str | None = None # Scryfall unreachable: deck not evaluated

    @property
    def is_valid(self) -> bool: ...  # also False when service_error is set
```

---

## SPG Rarity Overrides

See [caching.md](caching.md) for the details of the override system.

Quick flow:
1. `get_override_rarity(name)` checks `data/arena_rarity_data.json` (or the seed `seeds/arena_rarity.json`
   until the first SPG scan writes it)
2. If found as `"common"` or `"uncommon"` → card legal (skips the API)
3. Covers the SPG (Special Guests) cards that are rare/mythic on Arena but common/uncommon on paper
4. Refreshed automatically every week (`periodic_spg_refresh_loop`); can be forced right away with
   `/forced_rarity_refresh` (admin)

---

## Caching

See [caching.md](caching.md) for full details.

- `cached_cards` SQLite table: persistent Scryfall cache with the `artisan_legal` field
- Incremental save every 60 seconds, plus one last save at shutdown
- Decks already checked mostly hit the cache instead of the API
