# Validazione Mazzi Artisan

## Panoramica

Il sistema di validazione verifica che i mazzi rispettino le regole del formato **Artisan** (solo carte Common e Uncommon su MTG Arena). Combina banlist locale, API Scryfall, override di rarità SPG e caching intelligente.

---

## Struttura

```
cogs/deck_validation/
├── __init__.py           # ArtisanDeckCheckModal + Tournament cog
├── models.py             # DeckEntry, ArtisanCard, DeckValidationResult
├── validators.py         # parse_decklist(), check_banlist(), count validation
├── service.py            # ArtisanService.validate_deck()
└── embeds.py             # Embed builder per risultati validazione

utils/
├── card_cache.py         # Cache persistente Scryfall
├── arena_overrides.py    # Override rarità SPG
└── deck_image_generator.py  # Generazione immagine showcase
```

---

## Flusso di Validazione

```
                    DECK LIST (testo incollato dall'utente)
                                │
                                ▼
                    ┌───────────────────────┐
                    │   parse_decklist()     │
                    │   • estrae blocco About│
                    │   • separa main/side   │
                    │   • strip set code     │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │    check_banlist()     │
                    │   • O(1) lookup set    │
                    └───────────┬───────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
            BANNATE TROVATE         NESSUNA BANNATA
                    │                       │
                    ▼                       ▼
            DECK INVALIDO           ┌───────────────────────┐
            (stop, no API)          │  _fetch_collection()   │
                                    │  • cache check         │
                                    │  • Scryfall batch API  │
                                    └───────────┬───────────┘
                                                │
                                                ▼
                                    ┌───────────────────────┐
                                    │ _is_arena_artisan_     │
                                    │ legal() per ogni carta │
                                    │ • override SPG check   │
                                    │ • prints search Arena  │
                                    └───────────┬───────────┘
                                                │
                                    ┌───────────┴───────────┐
                                    ▼                       ▼
                            ILLEGALI TROVATE        TUTTE LEGALI
                                    │                       │
                                    ▼                       ▼
                            DECK INVALIDO           ┌───────────────────────┐
                                                    │ count validation      │
                                                    │ main >= 60, side<=15 │
                                                    └───────────┬───────────┘
                                                                │
                                                    ┌───────────┴───────────┐
                                                    ▼                       ▼
                                            CONTEGGIO ERRORE     CONTEGGIO OK
                                                    │                       │
                                                    ▼                       ▼
                                            DECK INVALIDO           ┌───────────────────────┐
                                                                    │ generate deck image   │
                                                                    │ pubblica embed        │
                                                                    └───────────────────────┘
```

---

## Componenti

### 1. Parser Decklist (`validators.py:25-55`)

`parse_decklist(text: str) -> tuple[str | None, list[DeckEntry], list[DeckEntry]]`

- Riconosce il blocco `About` per il nome del mazzo
- Separa mainboard e sideboard (righe vuote come separatore)
- Formatta: `3 Lightning Bolt (ONE) 123` → nome, quantità
- Strip il set code e collector number dal nome

### 2. Banlist Check (`validators.py:72-79`)

`check_banlist(entries, banlist) -> list[str]`

- Confronto case-insensitive (`nome.lower()`)
- O(1) lookup su `set[str]`
- Nessuna duplicazione nei risultati
- Se lista non vuota → deck invalido

### 3. Fetch Scryfall (`service.py:198-262`)

`async _fetch_collection(session, card_names)`

- Raggruppa carte non in cache
- Chiama `POST /cards/collection` in chunk da 75
- Aggiorna `card_cache.json` con i risultati
- Rate limiting: semaforo 1 richiesta, delay 110ms

### 4. Verifica Legalità Arena (`service.py:266-312`)

`async _is_arena_artisan_legal(session, card_data, card_name) -> bool`

Ordine dei controlli:
1. **Override locale** → `get_override_rarity(card_name)` → se common/uncommon → legale
2. **Cache disco** → `artisan_legal` field in `card_cache.json`
3. **Cache memoria** → `oracle_id` già verificato
4. **API Scryfall** → `GET prints_search_uri + ?game=arena`

Nella chiamata API:
- Filtra `set_type=alchemy` (escluso da Artisan)
- Controlla se esiste una stampa common/uncommon su Arena
- Salva risultato in cache (`artisan_legal`)

### 5. Conteggio (`validators.py:82-96`)

- Mainboard: minimo 60 carte
- Sideboard: massimo 15 carte
- Deck vuoto o nessun mainboard → invalido

### 6. Generazione Immagine (`utils/deck_image_generator.py`)

`DeckImageGenerator.create_deck_showcase(entries, sideboard, deck_name, player_name, color_identity) -> io.BytesIO`

- Seleziona sfondo per gilda/colore da `assets/backgrounds/`
- Scarica immagini carte da Scryfall
- Compositing: header, griglia mainboard, colonna sideboard
- Watermark logo Clepshydra in basso a destra

---

## Modelli Dati (`models.py`)

```python
@dataclass
class DeckEntry:
    name: str           # Nome carta
    quantity: int       # Quantità (default 1)
    set_code: str | None = None  # Set code opzionale

@dataclass
class ArtisanCard:
    name: str
    type_line: str
    cmc: float
    image_url: str | None
    artisan_legal: bool | None

@dataclass
class DeckValidationResult:
    is_valid: bool
    entries: list[DeckEntry]
    card_data: dict[str, ArtisanCard]
    banned_cartes: list[str]
    illegal_cartes: list[str]
    not_found_cartes: list[str]
    deck_name: str | None
```

---

## Override Rarità SPG

Vedi [banlist-system.md](banlist-system.md) per dettagli sul sistema di override.

Flusso rapido:
1. `get_override_rarity(nome)` controlla `arena_rarity_data.json`
2. Se trovato come `"common"` o `"uncommon"` → carta legale (salta API)
3. Contiene ~40 carte del set SPG (Special Guest)
4. Aggiornabile via `/update_spg_overrides` (admin)

---

## Caching

Vedi [caching.md](caching.md) per dettagli completi.

- `card_cache.json`: cache persistente Scryfall con field `artisan_legal`
- Salvataggio automatico ogni 60 secondi (scrittura atomica)
- Cache elimina ~90% delle chiamate API per deck già verificati
