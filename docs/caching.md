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
| `mark_artisan_legal(name, entry, legal)` | Imposta `artisan_legal` + `artisan_legal_checked_at` e salva la entry |
| `is_artisan_legal_stale(entry)` | `True` se manca il timestamp o è oltre `ARTISAN_LEGAL_TTL_DAYS` (30 giorni) |
| `invalidate_card(name)` | Rimuove una carta dalla cache (usato da `/invalidate_card_cache`) |
| `periodic_save_loop(delay=60)` | Task asincrono che salva ogni 60s se `_dirty` |

### Dettagli Implementativi

- `_dirty`: flag booleano che evita scritture su disco senza modifiche
- `_save_lock`: `asyncio.Lock()` per prevenire race-condition su scritture concorrenti
- Scrittura atomica: `json.dump` su file `.tmp`, poi `os.replace()` → file mai corrotto
- `_periodic_save_task`: avviato in `main.py:setup_hook()`

### TTL su `artisan_legal`

Il flag `artisan_legal` non è più considerato valido a tempo indeterminato. Ogni volta che
`_is_arena_artisan_legal()` (`cogs/deck_validation/service.py`) lo calcola, chiama
`mark_artisan_legal()` che salva anche `artisan_legal_checked_at` (timestamp ISO, UTC). Al check
successivo, se la entry cacheata ha `artisan_legal_checked_at` più vecchio di `ARTISAN_LEGAL_TTL_DAYS`
(30 giorni) o non ce l'ha affatto (entry cacheata prima dell'introduzione del TTL), il flag viene
considerato scaduto e la carta viene ri-verificata via Scryfall invece di fidarsi ciecamente della
cache — copre il caso di una carta la cui legalità Artisan cambia dopo una nuova stampa su Arena.

Per correggere una singola carta senza aspettare il TTL, l'admin può usare `/invalidate_card_cache
<carta>`, che rimuove l'intera entry (non solo `artisan_legal`): la prossima validazione rifà anche il
fetch dei dati base da Scryfall.

### Struttura JSON (`data/card_cache.json`)

```json
{
  "lightning bolt": {
    "name": "Lightning Bolt",
    "type_line": "Instant",
    "cmc": 1.0,
    "image_uris": { "small": "https://...", "normal": "https://..." },
    "prints_search_uri": "https://api.scryfall.com/cards/search?q=...",
    "artisan_legal": true,
    "artisan_legal_checked_at": "2026-09-11T12:00:00+00:00"
  },
  "doubling season": {
    "name": "Doubling Season",
    "type_line": "Enchantment",
    "cmc": 5.0,
    "image_uris": { "small": "https://...", "normal": "https://..." },
    "prints_search_uri": "https://api.scryfall.com/cards/search?q=...",
    "artisan_legal": false,
    "artisan_legal_checked_at": "2026-09-11T12:00:00+00:00"
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

La banlist (`BannedCard` in SQLite) è cacheata in memoria nella variabile di modulo
`_banlist_cache: set[str] | None` in `cogs/deck_validation/service.py`, condivisa da tutte le istanze
di `ArtisanService`.

| Aspetto | Dettaglio |
|---|---|
| Caricamento | Prima validazione dopo l'avvio (o dopo un'invalidazione): `await BanlistRepository.get_all_for_format()` |
| Validità | Fino alla prossima invalidazione esplicita |
| Invalida | `ArtisanService.reload_banlist()` (wrapper su `invalidate_banlist_cache()`), chiamato da `/banlist_aggiungi` e `/banlist_rimuovi` subito dopo la scrittura sul DB — l'effetto è visibile da tutte le istanze, non solo da quella su cui è chiamato |

---

## Riepilogo Cache

| Cache | Location | Persistenza | Invalidation |
|---|---|---|---|
| Carte Scryfall | `card_cache.json` | 60s (atomica) | Nessuna (crescita organica) |
| Override rarità | `arena_rarity_data.json` | Su aggiornamento | Esplicita (`invalidate_override_cache()`) |
| Banlist | `_banlist_cache` (modulo) | Condivisa tra istanze | Esplicita (`reload_banlist()` dopo add/remove) |
