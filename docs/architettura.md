# Architettura del Sistema

## Panoramica

ClepshydraBot adotta un'architettura **three-tier** con separazione netta delle responsabilità:

1. **Discord Layer (Cogs)** — Interfaccia utente, comandi slash, componenti interattivi
2. **Service Layer** — Logica di business, algoritmi, orchestrazione
3. **Repository Layer** — Accesso ai dati, CRUD, query

A questi si aggiungono il **Database Layer** (SQLAlchemy ORM) e il **Utilities Layer** (funzioni cross-cutting).

---

## Diagramma Architetturale

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DISCORD API (Gateway + REST)                  │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
┌─────────────────────────────────┴───────────────────────────────────┐
│  COGS (Controller)                                                   │
│                                                                       │
│  ┌─────────────────────┐  ┌──────────────────────┐                   │
│  │  PresentationCog    │  │  TournamentSystemCog  │                   │
│  │  /presentati        │  │  14 comandi slash     │                   │
│  │  on_member_join     │  │  modali, select menu  │                   │
│  └────────┬────────────┘  └───────────┬──────────┘                   │
│           │                            │                              │
│  ┌────────┴────────────┐  ┌───────────┴──────────┐                   │
│  │  TournamentCog      │  │  Logger               │                   │
│  │  /artisan_check_deck│  │  send_log()           │                   │
│  └────────┬────────────┘  └──────────────────────┘                   │
│           │                                                           │
│  ┌────────┴────────────┐                                             │
│  │  SPGOverrideUpdater │                                             │
│  │  /update_spg_overr. │                                             │
│  └─────────────────────┘                                             │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
┌─────────────────────────────────┴───────────────────────────────────┐
│  SERVICE LAYER (Business Logic)                                      │
│                                                                       │
│  ┌─────────────────────┐  ┌──────────────────────┐                   │
│  │  TournamentService  │  │  ArtisanService       │                   │
│  │  • create_tournament│  │  • validate_deck()    │                   │
│  │  • register_player  │  │  • _fetch_collection  │                   │
│  │  • start_tournament │  │  • _is_arena_legal    │                   │
│  │  • submit_result    │  └──────────────────────┘                   │
│  │  • generate_round   │                                              │
│  │  • force_drop       │  ┌──────────────────────┐                   │
│  │  • force_conclude   │  │  PresentationService  │                   │
│  │  • get_standings    │  │  • publish()          │                   │
│  └────────┬────────────┘  │  • assign_roles()     │                   │
│           │               └──────────────────────┘                   │
│  ┌────────┴────────────┐                                              │
│  │  PairingEngine      │  ┌──────────────────────┐                   │
│  │  • generate_round() │  │  StandingsCalculator  │                   │
│  │  • calculate_rounds │  │  • compute()          │                   │
│  └─────────────────────┘  └──────────────────────┘                   │
│                                                                       │
│  ┌─────────────────────┐                                              │
│  │  Rating (Glicko-2)  │                                              │
│  │  • rate_1vs1()      │                                              │
│  │  • rate_draw()      │                                              │
│  └─────────────────────┘                                              │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
┌─────────────────────────────────┴───────────────────────────────────┐
│  REPOSITORY LAYER (Data Access)                                      │
│                                                                       │
│  ┌─────────────────────┐  ┌──────────────────────┐                   │
│  │  BaseRepository[T]  │  │  UserRepository      │                   │
│  │  • get_by_id        │  │  • get_by_discord_id │                   │
│  │  • list_all         │  │  • get_or_create     │                   │
│  │  • add              │  │  • get_leaderboard   │                   │
│  │  • delete           │  └──────────────────────┘                   │
│  │  • count            │                                              │
│  └─────────────────────┘  ┌──────────────────────┐                   │
│                            │  TournamentRepository│                   │
│  ┌─────────────────────┐  │  • get_by_status     │                   │
│  │  MatchRepository    │  │  • get_with_players  │                   │
│  │  • get_by_tournament│  └──────────────────────┘                   │
│  │  • get_current_round│                                              │
│  │  • get_pairings_for │  ┌──────────────────────┐                   │
│  └─────────────────────┘  │  BanlistRepository   │                   │
│                            │  • get_all_for_format│                   │
│  ┌─────────────────────┐  │  • add_card          │                   │
│  │  TournamentPlayer   │  │  • remove_card       │                   │
│  │  Repository         │  │  • import_from_file  │                   │
│  └─────────────────────┘  └──────────────────────┘                   │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
┌─────────────────────────────────┴───────────────────────────────────┐
│  DATABASE / EXTERNAL APIs                                           │
│                                                                       │
│  ┌─────────────────────┐  ┌──────────────────────┐                   │
│  │  SQLite             │  │  Scryfall API         │                   │
│  │  tables:            │  │  • /cards/collection  │                   │
│  │  • users            │  │  • /cards/search      │                   │
│  │  • tournaments      │  └──────────────────────┘                   │
│  │  • tournament_players│                                            │
│  │  • matches          │  ┌──────────────────────┐                   │
│  │  • banned_cards     │  │  Discord API          │                   │
│  └─────────────────────┘  │  • Gateway WebSocket  │                   │
│                            │  • REST API           │                   │
│                            └──────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Pattern Utilizzati

| Pattern | Dove | Descrizione |
|---|---|---|
| **Repository** | `repositories/` | Astrae l'accesso ai dati dietro interfacce dedicate |
| **Service Layer** | `services/` | Incapsula la logica di business in classi service |
| **Strategy** | `PairingEngine`, `StandingsCalculator` | Algoritmi intercambiabili e stateless |
| **Observer** | Cogs `on_member_join`, `on_message` | Listener per eventi Discord |
| **Dependency Injection** | Costruttori service | Bot e session passati via costruttore |
| **Singleton** | `database/engine.py` | Engine e session factory globali con lazy init |
| **Data Mapper** | `database/models.py` | SQLAlchemy ORM con classi modello esplicite |
| **MVP-like** | Cog = Controller, Service = Model, Embed = View | Separazione UI/logica |

---

## Flussi Principali

### Presentazione Utente

```
User joins server
  → on_member_join() → ruolo 'Viandante' + messaggio welcome
  → /presentati
    → BasicPresentationModal (5 campi)
    → PreferencesView (4 select menu)
    → OptionalPresentationModal (4 campi opzionali)
    → PreviewView (conferma/cancella)
    → PresentationService.publish()
      → Validazione campi
      → Cambio ruolo: Viandante → Planeswalker
      → Embed pubblicato su canale presentazioni
      → Logger.send_log(INFO)
```

### Validazione Mazzo Artisan

```
User → /artisan_check_deck → ArtisanDeckCheckModal
  → ArtisanService.validate_deck()
    1. _load_banlist() ← BanlistRepository (SQLite)
    2. check_banlist() → se banned → STOP
    3. _fetch_collection() → Scryfall API (o cache)
    4. _is_arena_artisan_legal() per ogni carta
       → arena_overrides (SPG check)
       → prints_search_uri + game:arena
    5. Conteggio: mainboard >= 60, sideboard <= 15
  → DeckValidationResult
  → DeckImageGenerator.create_deck_showcase() (se valido)
  → Embed + immagine → canali log e deck
```

### Ciclo di Vita Torneo

```
Admin → /crea_torneo → TournamentService.create_tournament()
User  → /iscriviti → IscrivitiModal (deck validation) → register_player()
Admin → /avvia_torneo → start_tournament()
  → PairingEngine.generate_round(1) → pairing casuali
  → Embed pubblicato su canale torneo
[Round giocato]
User  → /risultato → RisultatoView → submit_result()
Admin → /torneo_next_turn → generate_next_round()
  → Se ultimo round → conclude torneo → _update_ratings() (Glicko-2)
  → Altrimenti → PairingEngine.generate_round(N) → pairing Swiss
User  → /classifica → StandingsCalculator.compute() (3/1/0 + tiebreaker)
```

---

## Gestione Errori

- **Catch-all**: ogni comando slash ha `try/except` con log ERROR
- **Retry**: chiamate Scryfall con backoff esponenziale (max 5 tentativi)
- **Rate limiting**: semaforo asyncio per rispettare limiti Scryfall
- **Scrittura atomica**: cache JSON scritta su `.tmp` poi `os.replace()`
- **Lock asincrono**: `asyncio.Lock()` per salvataggio cache concorrente
