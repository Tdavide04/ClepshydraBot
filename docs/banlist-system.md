# Sistema Banlist Carte Magic — Clepshydra Bot

## Panoramica

Il sistema gestisce le carte bandite nel formato **Artisan** (solo carte Common e Uncommon su MTG Arena). La banlist è un elenco di carte che, pur essendo di rarità comune o non comune, sono bandite perché considerate troppo forti per il formato.

---

## Architettura

```
┌─────────────────────────────────────────────────────────┐
│                    Avvio Bot                            │
│  database/engine.py:_migrate_banlist()                  │
│    → importa cards.txt nel DB SQLite                    │
│    → solo se il DB è vuoto                              │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│             BanlistRepository                           │
│  repositories/banlist_repository.py                     │
│  • CRUD su tabella banned_cards                         │
│  • get_all_for_format() → set[str]                     │
│  • add_card() / remove_card()                           │
│  • import_from_file()                                   │
└──────────────────────┬──────────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌──────────────────┐    ┌──────────────────────────────┐
│  Tournaments     │    │  Slash Commands (Admin)       │
│  (deck check)    │    │  /banlist                     │
│                  │    │  /banlist_aggiungi            │
│                  │    │  /banlist_rimuovi             │
└──────────────────┘    └──────────────────────────────┘
```

---

## Componenti nel dettaglio

### 1. Seed Data — `cards.txt`

File di testo con 220 carte bandite, una per riga. Include:
- Carte con prefisso `A-` (versione Alchemy su Arena)
- Carte double-faced (`Nome // Nome`)
- Carte "normali" bandite (es. `Abiding Grace`, `Mishra's Bauble`)

### 2. Migrazione all'avvio — `database/engine.py:51-66`

Allo startup, `_migrate_banlist()`:
1. Controlla se `cards.txt` esiste
2. Chiama `BanlistRepository.import_from_file()`
3. Se il DB è vuoto, importa tutte le carte con format=`"Artisan"`
4. Se il DB ha già dati, salta l'import (non duplica)

### 3. Modello Dati — `database/models.py:99-108`

```python
class BannedCard(Base):
    __tablename__ = "banned_cards"

    id          = Column(Integer, primary_key=True)
    card_name   = Column(String(200), unique=True, index=True)  # nome esatto
    format      = Column(String(50), default="Artisan")         # formato di appartenenza
    created_at  = Column(DateTime, default=datetime.now)
```

### 4. Repository — `repositories/banlist_repository.py`

| Metodo | Funzione |
|---|---|
| `get_all_for_format(format="Artisan")` | Restituisce un `set[str]` con tutti i nomi (lowercase) delle carte bandite per il formato |
| `add_card(card_name, format="Artisan")` | Aggiunge una carta alla banlist |
| `remove_card(card_name)` | Rimuove una carta per nome esatto, ritorna `True/False` |
| `count()` | Numero totale di carte bandite |
| `import_from_file(path)` | Importa bulk da file di testo (solo se DB vuoto) |

### 5. Validazione Deck — `cogs/tournament/service.py:48-65`

`ArtisanService.validate_deck()`:
1. Alla prima chiamata, carica la banlist in memoria via `_load_banlist()` → `BanlistRepository.get_all_for_format()`
2. Chiama `check_banlist(entries, self._banlist)` (da `cogs/tournament/validators.py:72-79`)
3. Se trova carte bandite, restituisce subito `DeckValidationResult(banned_cards=[...])` → deck **invalido**
4. Se nessuna carta bandita, prosegue con la validazione rarità (API Scryfall)

### 6. Check Banlist — `cogs/tournament/validators.py:72-79`

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

Logica:
- Itera ogni carta del deck
- Confronta il nome (lowercase) con la banlist
- Se matcha, aggiunge alla lista dei risultati (senza duplicati)
- Se la lista risultante non è vuota → deck invalido

### 7. Load Banlist da File (legacy) — `cogs/tournament/validators.py:10-22`

Funzione `load_banlist()` usata **solo come utility standalone** (non più chiamata dal flusso principale dal vivo):
- Legge `cards.txt` riga per riga
- Per le carte double-faced (` // `), aggiunge anche solo il nome frontale
- Restituisce `set[str]` (lowercase)

### 8. Slash Commands — `cogs/tournament_system/cog.py:1053-1154`

| Comando | Descrizione | Permessi |
|---|---|---|
| `/banlist` | Mostra tutte le carte bandite in embed paginato (30 per field) | Pubblico |
| `/banlist_aggiungi <carta>` | Aggiunge una carta al DB | `@is_admin()` (ruolo `Staff`) |
| `/banlist_rimuovi <carta>` | Rimuove una carta dal DB | `@is_admin()` |

### 9. Embed di Risultato — `cogs/tournament/embeds.py`

Se il deck ha carte bandite, l'embed mostra:
- **Carte Bannate**: elenco (max 10)
- **Resoconto**: conteggio carte bannate
- Colore rosso (`is_valid = False`)

### 10. Caching

La banlist non ha un caching esplicito oltre al campo `self._banlist: set[str]` in `ArtisanService`. Viene caricata dal DB alla prima validazione e tenuta in memoria per l'intera vita dell'istanza.

---

## Flusso Completo (Deck Check con Banlist)

```
Utente invia deck
    → TournamentSystemCog.registra() o /deck_check
        → ArtisanService.validate_deck()
            → _load_banlist()  (se non già in memoria)
                → BanlistRepository.get_all_for_format()
                    → SELECT card_name FROM banned_cards WHERE format = 'Artisan'
            → check_banlist(entries, banlist)
                → [nome1, nome2, ...]  oppure []
            ↓
    ┌───────┴───────┐
    │ banned != []   │  banned == []
    │                │
    ▼                ▼
Deck INVALIDO    Deck OK
(bannate trovate) → prosegue con
                    validazione rarità
                    (API Scryfall)
```

---

## API Esterne

Il sistema di banlist **non chiama API esterne**. Usa esclusivamente:
- **File locale** `cards.txt` per il seed iniziale
- **Database SQLite** per lo storage persistente
- Il confronto è puramente testuale (`nome.lower() in banlist`)

Le API Scryfall sono usate nella fase successiva (validazione rarità Artisan), non per la banlist.

---

## Sistema di Validazione Rarità Artisan

Dopo aver superato il controllo banlist, ogni carta del deck viene verificata contro le API Scryfall per determinare se è legale nel formato Artisan (solo carte Common e Uncommon su MTG Arena). Quattro componenti lavorano insieme per questo scopo.

---

### Componenti

```
┌──────────────────────────────────────────────────────────────────┐
│                     ArtisanService.validate_deck()                │
│   cogs/tournament/service.py                                      │
│                                                                    │
│   1. check_banlist() ──── ok? ───→ 2. _fetch_collection()         │
│                                        ↓                          │
│                                    3. _is_arena_artisan_legal()    │
│                                        ↓                          │
│                          ┌───────────┴───────────┐                │
│                          ▼                       ▼                │
│              utils/arena_overrides.py   utils/card_cache.py       │
│              data/arena_rarity_data.json  data/card_cache.json    │
└──────────────────────────────────────────────────────────────────┘
```

---

### `utils/arena_overrides.py` — Override di rarità

**Problema**: Alcune carte esistono in versione Common/Uncommon su carta (paper), ma su MTG Arena sono state stampate solo con rarità Rare/Mythic (es. le Special Guest — set `SPG`). Scryfall le vedrebbe come Rare, ma nel formato Artisan dovrebbero essere considerate legali in base alla loro rarità paper più bassa.

**Soluzione**: Il modulo mantiene un dizionario di override che forza una rarità più bassa per queste carte.

| Funzione | Ruolo |
|---|---|
| `get_override_rarity(card_name)` | API pubblica: restituisce `"common"`/`"uncommon"` o `None` |
| `update_spg_overrides(set_code="spg")` | Scansione Scryfall: trova carte stampate su Arena a rarità alta ma con versioni paper a rarità bassa |
| `invalidate_override_cache()` | Forza il ricaricamento del JSON al prossimo accesso |

**Caching**: Il JSON viene caricato una volta in `_override_cache` (variabile globale) e tenuto in memoria. `_save_override_data()` aggiorna sia il file su disco che la cache.

**Utilizzo nel flusso** (`_is_arena_artisan_legal()` in `service.py:266-312`):
1. Chiama `get_override_rarity(card_name)`
2. Se l'override è `"common"` o `"uncommon"` → carta legale, salta la chiamata API
3. Altrimenti procede con la scansione Scryfall delle stampe

---

### `data/arena_rarity_data.json` — Storage override

```json
{
    "processed_sets": ["SPG"],
    "overrides": {
        "Swords to Plowshares": "uncommon",
        "Lightning Bolt": "common",
        "Sylvan Library": "uncommon",
        ...
    }
}
```

| Campo | Descrizione |
|---|---|
| `processed_sets` | Set già scansionati da `update_spg_overrides()`. Un set presente qui non verrà riscansionato. |
| `overrides` | Dizionario `nome_carta → rarità_forzata`. Contiene attualmente ~40 carte del set SPG (Special Guest). |

**Attenzione**: Se all'avvio il JSON contiene già `"SPG"` in `processed_sets`, `update_spg_overrides()` salterà la scansione. Per forzare una nuova scansione:
1. Chiamare `invalidate_override_cache()`
2. Rimuovere `"SPG"` da `processed_sets` nel JSON
3. Eseguire `update_spg_overrides()`

---

### `utils/card_cache.py` — Cache Scryfall in memoria

Cache chiave-valore (nome carta lowercase → dati Scryfall) che evita di richiamare le API per carte già viste.

| Funzione | Ruolo |
|---|---|
| `load_cache()` | Carica `data/card_cache.json` in `_card_cache` (una volta sola) |
| `save_cache()` | Scrive su disco con scrittura atomica (file `.tmp` + `os.replace`) |
| `get_cached_card(name)` | Restituisce il dict Scryfall di una carta, o `None` |
| `set_cached_card(name, data)` | Aggiunge/aggiorna una carta nella cache; marca `_dirty = True` |
| `periodic_save_loop()` | Salva automaticamente ogni 60 secondi se ci sono modifiche |

**Dettagli implementativi**:
- `_dirty`: flag che evita scritture su disco se non ci sono state modifiche
- `_save_lock`: `asyncio.Lock()` per evitare race-condition su scritture concorrenti
- Scrittura atomica: `json.dump` su file `.tmp`, poi `os.replace()` → nessun file corrotto se il bot crasha durante il salvataggio

---

### `data/card_cache.json` — Cache persistente su disco

Contiene i dati delle carte già fetchate da Scryfall durante le validazioni dei deck.

**Struttura tipica** (una voce per carta, chiave = nome lowercase):

```json
{
  "goblin bushwhacker": {
    "name": "Goblin Bushwhacker",
    "type_line": "Creature — Goblin Warrior",
    "cmc": 1.0,
    "prints_search_uri": "https://...",
    "artisan_legal": true,
    "image_uris": { "small": "https://...", ... }
  }
}
```

**Dati memorizzati per carta**:
- `name`, `type_line`, `cmc` — usati per costruire l'embed e le card object
- `image_uris` — usato per generare l'immagine del deck (`DeckImageGenerator`)
- `prints_search_uri` — usato da `_is_arena_artisan_legal()` per fetchare le stampe
- `artisan_legal` — flag calcolato (cached) che indica se la carta è legale in Artisan
- Per le carte double-faced: l'intero oggetto Scryfall (`card_faces`, `layout`, ecc.)

**Dimensione**: Il file cresce organicamente col tempo. Ogni nuova carta vista durante una validazione deck viene aggiunta. Non c'è un meccanismo di pulizia/expiry.

---

### Flusso completo (banlist + validazione rarità + cache)

```
Utente invia deck
    → TournamentSystemCog (/deck_check o registrazione torneo)
        → ArtisanService.validate_deck()
            │
            ├─ 1. _load_banlist() ← BanlistRepository (SQLite)
            ├─ 2. check_banlist(entries, banlist)
            │      ↓
            │   Se banned → DeckValidationResult(banned_cards=[...]) → STOP
            │
            └─ 3. _fetch_collection(session, unique_names)
            │      │
            │      ├─ get_cached_card(nome) → se presente, salta API
            │      └─ POST /cards/collection (Scryfall, chunk 75)
            │             ↓
            │         set_cached_card(nome, data) per ogni carta
            │
            └─ 4. _is_arena_artisan_legal(session, data, nome)
                     │
                     ├─ get_override_rarity(nome) ← arena_rarity_data.json
                     │      ↓
                     │   Se override → True/False (senza API)
                     │
                     └─ GET prints_search_uri + game:arena (Scryfall)
                            ↓
                        Controlla rarità di ogni stampa su Arena
                        Se esiste comune/uncommon → legale
                        Altrimenti → illegale
                            ↓
                        Cache: set_cached_card(... "artisan_legal": bool)
```

---

## Problemi Noti / Potenziali

1. **Double-faced cards**: La banlist in `cards.txt` include già il nome completo (`A-Blessed Hippogriff // A-Tyr's Blessing`). Il `check_banlist()` si basa sul nome così come viene parsato dal deck — a sua volta, `parse_decklist()` tronca al ` // ` e prende solo il fronte. **Se un utente scrive il nome completo nel deck, il confronto potrebbe fallire** e la carta bannata passare inosservata.

2. **Aggiornamento live**: Se un admin aggiunge/rimuove una carta via slash command, il `self._banlist` in `ArtisanService` non viene invalidato. La nuova carta non sarà considerata fino al prossimo riavvio del bot (o finché `_load_banlist()` non viene richiamato).  
   **Fix suggerito**: Dopo `add_card`/`remove_card`, fare `self._banlist = await repo.get_all_for_format()` nel service.

3. **Case sensitivity**: Tutto è normalizzato in lowercase, quindi non ci sono problemi.
