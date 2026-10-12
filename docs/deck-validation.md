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
2. **Cache disco** → `artisan_legal` field in `card_cache.json`, **solo se non scaduto**
   (`is_artisan_legal_stale()`, TTL 30 giorni — vedi `docs/caching.md`); una entry senza
   `artisan_legal_checked_at` (cacheata prima dell'introduzione del TTL) è considerata scaduta
3. **Cache memoria** → `oracle_id` già verificato (`_ARENA_LEGAL_CACHE`, per la durata del processo —
   non soggetta a TTL)
4. **API Scryfall** → `GET prints_search_uri + ?game=arena`

Nella chiamata API:
- Filtra `set_type=alchemy` (escluso da Artisan)
- Controlla se esiste una stampa common/uncommon su Arena
- Salva risultato in cache con timestamp (`mark_artisan_legal()`)

### Scryfall non raggiungibile

`_request_with_retry()` (usata da `_post_with_retry`/`_get_with_retry`) distingue due esiti che fino alla
3.5.6 diventavano entrambi `None`:

- **404** → `{"data": []}`: su `/cards/search` significa "nessuna stampa trovata", quindi la carta non ha
  stampe Arena ed è **illegale** — esito valido, memorizzato in cache come prima
- **errore di rete, timeout, 5xx o 429 oltre i 5 tentativi, altro status inatteso** → solleva
  `ScryfallUnavailable`. I 5xx vengono ora ritentati con backoff come i timeout (prima: abbandono immediato)

`validate_deck()` intercetta `ScryfallUnavailable` e restituisce un `DeckValidationResult` con
`service_error` valorizzato e nessuna carta in `invalid_cards`/`illegal_rarity_cards`: il mazzo **non è
stato valutato**, né valido né invalido. Nessuna cache viene toccata. `/invia_deck` e
`/artisan_check_deck` rispondono "Scryfall non risponde, riprova tra qualche minuto" (l'iscrizione al
torneo resta invariata) e loggano `WARN` `SCRYFALL_UNAVAILABLE`.

Prima della 3.5.7 un singolo timeout sulla ricerca stampe salvava la carta come illegale in
`_ARENA_LEGAL_CACHE` fino al riavvio del bot (ogni mazzo che la conteneva veniva rifiutato con "Non legali
in Artisan Arena"), e un blocco `/cards/collection` fallito faceva comparire le sue carte in "Carte non
trovate".

Per forzare un ricontrollo immediato di una singola carta (senza aspettare il TTL), l'admin può usare
`/invalidate_card_cache <carta>`.

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
    invalid_cards: list[str]         # "Carte non trovate"
    illegal_rarity_cards: list[str]  # "Non legali in Artisan Arena"
    mainboard: list[ArtisanCard]
    sideboard: list[ArtisanCard]
    service_error: str | None = None # Scryfall non raggiungibile: mazzo non valutato

    @property
    def is_valid(self) -> bool: ...  # False anche se service_error e' valorizzato
```

---

## Override Rarità SPG

Vedi [banlist-system.md](banlist-system.md) per dettagli sul sistema di override.

Flusso rapido:
1. `get_override_rarity(nome)` controlla `arena_rarity_data.json`
2. Se trovato come `"common"` o `"uncommon"` → carta legale (salta API)
3. Contiene ~40 carte del set SPG (Special Guest)
4. Aggiornato automaticamente ogni settimana (`periodic_spg_refresh_loop`); forzabile subito via `/forced_rarity_refresh` (admin)

---

## Caching

Vedi [caching.md](caching.md) per dettagli completi.

- `card_cache.json`: cache persistente Scryfall con field `artisan_legal`
- Salvataggio automatico ogni 60 secondi (scrittura atomica)
- Cache elimina ~90% delle chiamate API per deck già verificati
