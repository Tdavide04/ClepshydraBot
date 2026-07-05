# Cache e API Esterne

## Panoramica

ClepshydraBot interagisce con **Scryfall API** per la validazione dei mazzi Artisan. Per minimizzare le chiamate HTTP e rispettare i rate limit, implementa un sistema di caching a tre livelli.

---

## Architettura Cache

```
┌──────────────────────────────────────────────────────────────┐
│                     Richiesta Carta                           │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Livello 1: Override Rarità (arena_overrides.py)              │
│  • Cache in-memory (_override_cache)                          │
│  • arena_rarity_data.json (persistente)                       │
│  • Solo per SPG / carte con discrepanza Arena-Paper           │
└────────────────────────┬─────────────────────────────────────┘
                         │
                    ┌────┴────┐
                    ▼         ▼ (override non trovato)
              RETURN        CONTINUA
              (legal)           │
                                ▼
              ┌────────────────────────────────────────────────┐
              │  Livello 2: Cache Scryfall (card_cache.py)     │
              │  • Cache in-memory (_card_cache dict)          │
              │  • card_cache.json (persistente, 60s save)     │
              │  • artisan_legal field già calcolato           │
              └──────────────────┬─────────────────────────────┘
                                 │
                            ┌────┴────┐
                            ▼         ▼ (cache miss)
                      RETURN        CONTINUA
                      (legal/            │
                       illegal)          ▼
                      ┌────────────────────────────────────────┐
                      │  Livello 3: API Scryfall Live          │
                      │  • POST /cards/collection (batch 75)   │
                      │  • GET prints_search_uri + game:arena  │
                      │  • Rate limiting + retry               │
                      │  • Risultato salvato in cache          │
                      └────────────────────────────────────────┘
```

---

## 1. Cache Carte Scryfall (`utils/card_cache.py`)

### Funzioni

| Funzione | Descrizione |
|---|---|
| `load_cache()` | Carica `data/card_cache.json` in `_card_cache` (una volta all'avvio) |
| `save_cache()` | Scrittura atomica su disco: `.tmp` + `os.replace()` |
| `get_cached_card(name)` | Restituisce dati Scryfall di una carta o `None` |
| `set_cached_card(name, data)` | Aggiunge/aggiorna carta; marca `_dirty = True` |
| `periodic_save_loop(delay=60)` | Task asincrono che salva ogni 60s se `_dirty` |

### Dettagli Implementativi

- `_dirty`: flag booleano che evita scritture su disco senza modifiche
- `_save_lock`: `asyncio.Lock()` per prevenire race-condition su scritture concorrenti
- Scrittura atomica: `json.dump` su file `.tmp`, poi `os.replace()` → file mai corrotto
- `_periodic_save_task`: avviato in `main.py:setup_hook()`

### Struttura JSON (`data/card_cache.json`)

```json
{
  "lightning bolt": {
    "name": "Lightning Bolt",
    "type_line": "Instant",
    "cmc": 1.0,
    "image_uris": { "small": "https://...", "normal": "https://..." },
    "prints_search_uri": "https://api.scryfall.com/cards/search?q=...",
    "artisan_legal": true
  },
  "doubling season": {
    "name": "Doubling Season",
    "type_line": "Enchantment",
    "cmc": 5.0,
    "image_uris": { "small": "https://...", "normal": "https://..." },
    "prints_search_uri": "https://api.scryfall.com/cards/search?q=...",
    "artisan_legal": false
  }
}
```

---

## 2. Override Rarità SPG (`utils/arena_overrides.py`)

### Problema

Carte del set **SPG (Special Guests)** stampate su carta a rarità common/uncommon, ma apparse su Arena solo a rarità rare/mythic. Scryfall le vedrebbe come illegali per Artisan, ma dovrebbero essere legali in base alla rarità paper più bassa.

### Soluzione

Dizionario di override che forza una rarità più bassa per queste carte.

| Funzione | Descrizione |
|---|---|
| `get_override_rarity(card_name)` | Restituisce `"common"`, `"uncommon"` o `None` |
| `update_spg_overrides(set_code="spg")` | Scansione Scryfall, aggiorna JSON |
| `invalidate_override_cache()` | Forza ricarica del JSON al prossimo accesso |

### Cache In-Memory

`_override_cache`: variabile globale popolata al primo accesso. Invalidabile esplicitamente.

### Struttura JSON (`data/arena_rarity_data.json`)

```json
{
  "processed_sets": ["SPG"],
  "overrides": {
    "Swords to Plowshares": "uncommon",
    "Lightning Bolt": "common",
    "Sylvan Library": "uncommon"
  }
}
```

Nota: `processed_sets` evita ri-scansioni. Per forzare: rimuovere il set dal JSON e chiamare `update_spg_overrides()`.

---

## 3. Scryfall API — Strategia

### Endpoint

| Endpoint | Utilizzo | Limite |
|---|---|---|
| `POST /cards/collection` | Fetch batch di carte (max 75 per chunk) | 100ms tra richieste |
| `GET prints_search_uri + game:arena` | Verifica stampe Arena per singola carta | — |

### Rate Limiting

```python
_semaphore = asyncio.Semaphore(1)  # 1 richiesta alla volta
_min_delay = 0.11  # 110ms tra richieste (supera il limite 100ms)
```

### Retry Logic

- Backoff esponenziale su status 429 (leggendo header `Retry-After`)
- Timeout: 10s per richiesta
- Massimo 5 tentativi per richiesta

### Alchemy Filter

Le carte con `set_type=alchemy` sono escluse esplicitamente (non ammesse in Artisan). Il filtro viene applicato nella query `game:arena` ai risultati di `prints_search_uri`.

---

## 4. Cache Banlist

La banlist (`BannedCard` in SQLite) è cacheata in memoria in `ArtisanService._banlist: set[str]`.

| Aspetto | Dettaglio |
|---|---|
| Caricamento | Prima validazione: `await BanlistRepository.get_all_for_format()` |
| Validità | Per tutta la vita dell'istanza |
| Invalida | Solo al prossimo riavvio (noto: non si aggiorna dopo add/remove via slash) |
| Fix suggerito | Ricaricare `self._banlist` dopo `add_card`/`remove_card` |

---

## Riepilogo Cache

| Cache | Location | Persistenza | Invalidation |
|---|---|---|---|
| Carte Scryfall | `card_cache.json` | 60s (atomica) | Nessuna (crescita organica) |
| Override rarità | `arena_rarity_data.json` | Su aggiornamento | Esplicita (`invalidate_override_cache()`) |
| Banlist | `ArtisanService._banlist` | Per istanza | Riavvio (bug noto) |
