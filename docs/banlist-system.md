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

## Problemi Noti / Potenziali

1. **Double-faced cards**: La banlist in `cards.txt` include già il nome completo (`A-Blessed Hippogriff // A-Tyr's Blessing`). Il `check_banlist()` si basa sul nome così come viene parsato dal deck — a sua volta, `parse_decklist()` tronca al ` // ` e prende solo il fronte. **Se un utente scrive il nome completo nel deck, il confronto potrebbe fallire** e la carta bannata passare inosservata.

2. **Aggiornamento live**: Se un admin aggiunge/rimuove una carta via slash command, il `self._banlist` in `ArtisanService` non viene invalidato. La nuova carta non sarà considerata fino al prossimo riavvio del bot (o finché `_load_banlist()` non viene richiamato).  
   **Fix suggerito**: Dopo `add_card`/`remove_card`, fare `self._banlist = await repo.get_all_for_format()` nel service.

3. **Case sensitivity**: Tutto è normalizzato in lowercase, quindi non ci sono problemi.
