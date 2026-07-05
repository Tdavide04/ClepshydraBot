# ClepshydraBot — Resoconto Tecnico

**Versione 1.0.0 — Giugno 2026**  
**Autore: tdavide — Confidenziale**

---

## Infrastruttura

| Campo | Valore |
|---|---|
| Provider | Oracle Cloud Infrastructure |
| Regione | eu-milan-1 (Milano, Italia) |
| Shape | VM.Standard.E2.1.Micro |
| CPU / RAM | 1 OCPU — 1 GB RAM |
| Sistema | Canonical Ubuntu 24.04 LTS |
| IP Pubblico | 80.225.91.142 |

---

## Indice

1. [Panoramica del Progetto](#1-panoramica-del-progetto)
2. [Infrastruttura e Ambiente di Esecuzione](#2-infrastruttura-e-ambiente-di-esecuzione)
3. [Stack Tecnologico](#3-stack-tecnologico)
4. [Struttura del Repository](#4-struttura-del-repository)
5. [Funzionalità Implementate](#5-funzionalità-implementate)
6. [Sistema di Cache e Dati Persistenti](#6-sistema-di-cache-e-dati-persistenti)
7. [Interazione con API Esterne](#7-interazione-con-api-esterne)
8. [Flusso di una Verifica Mazzo Artisan](#8-flusso-di-una-verifica-mazzo-artisan)
9. [Limitazioni Attuali e Debito Tecnico](#9-limitazioni-attuali-e-debito-tecnico)
10. [Architettura V2](#10-architettura-v2)
11. [Roadmap — ClepshydraBot V2](#11-roadmap--clepshydrabot-v2)

---

## 1. Panoramica del Progetto

ClepshydraBot è un bot Discord sviluppato in Python per gestire una community dedicata a Magic: The Gathering Arena. Il bot automatizza tre aree principali:

- **Censimento e verifica utenti** al loro ingresso nel server
- **Validazione dei mazzi** per il formato Artisan tramite l'API di Scryfall
- **Generazione di immagini** personalizzate per il showcase dei mazzi verificati
- **Gestione tornei** con sistema Swiss, classifiche e rating Glicko-2

Il progetto nasce come strumento interno per la community Clepshydra. La V1 originale (bot monolitico) è stata completamente riscritta in V2 con un'architettura a layer separati, database relazionale SQLite e sistema torneo Swiss completo.

---

## 2. Infrastruttura e Ambiente di Esecuzione

### 2.1 Oracle Cloud Infrastructure (OCI)

| Campo | Valore |
|---|---|
| Provider | Oracle Cloud Infrastructure — Free Tier |
| Regione | eu-milan-1 (AD-1, Fault Domain: FD-2) |
| OCID Istanza | `ocid1.instance.oc1.eu-milan-1.anwgsljrtzu6yzqc...` |
| Data di avvio | 4 Maggio 2026, 20:29:36 UTC |
| IP Pubblico | 80.225.91.142 |
| Username SSH | ubuntu |
| Accesso | SSH con chiave privata |

### 2.2 Specifiche Hardware

| Specifica | Valore |
|---|---|
| Shape | VM.Standard.E2.1.Micro |
| OCPU | 1 (non ridimensionabile) |
| RAM | 1 GB |
| Rete | 0.5 Gbps |
| Storage | Block Storage only (nessun disco locale) |
| Crittografia | In-transit encryption abilitata |
| Firmware | UEFI_64 |
| Launch Mode | PARAVIRTUALIZED |

### 2.3 Sistema Operativo

| Specifica | Valore |
|---|---|
| OS | Canonical Ubuntu 24.04 LTS |
| Immagine | Canonical-Ubuntu-24.04-2026.03.31-0 |
| Secure Boot | Disabilitato |
| Measured Boot | Disabilitato |
| TPM | Disabilitato |
| IMDS | Version 2 only |

**Nota**: con 1 GB di RAM il bot è progettato per minimizzare il consumo di memoria. Questo vincolo architetturale ha guidato la scelta di SQLite over PostgreSQL e l'uso di cache JSON leggere invece di soluzioni in-memory come Redis.

---

## 3. Stack Tecnologico

### 3.1 Dipendenze Python

| Libreria | Ruolo |
|---|---|
| `discord.py` | Libreria principale per l'integrazione con l'API Discord. Gestisce slash commands, modal, select menu, eventi e cog. |
| `aiohttp` | Client HTTP asincrono per le chiamate all'API Scryfall. Usato con retry logic e rate limiting. |
| `Pillow (PIL)` | Generazione immagini per il deck showcase: compositing delle card art, sfondi, watermark logo, testi. |
| `python-dotenv` | Caricamento variabili d'ambiente dal file `.env`. |
| `SQLAlchemy` | ORM asincrono per SQLite. |
| `aiosqlite` | Driver asincrono per SQLite. |

### 3.2 Servizi Esterni

| Servizio | Utilizzo |
|---|---|
| Discord API | Gateway WebSocket per ricezione eventi + REST API per invio messaggi, embed, file. |
| Scryfall API | `POST /cards/collection` per fetch batch di carte. `GET prints_search_uri` per verifica legalità Arena. Rate limit: 100ms tra richieste. |

### 3.3 Versioni

| Componente | Versione |
|---|---|
| Python | 3.12+ |
| discord.py | Latest stable |
| Bot | 1.0.0 |

---

## 4. Struttura del Repository

```
clepshydrabot/
├── main.py                          # Entry point del bot
├── requirements.txt                 # Dipendenze Python
├── .env                             # Variabili d'ambiente (non in git)
│
├── cogs/                            # Moduli Discord (Cog)
│   ├── logger.py                    # Sistema di logging su canale Discord
│   ├── spg_override_updater.py      # Aggiornamento override rarità SPG
│   ├── presentation/                # Sistema presentazioni (multi-step wizard)
│   │   ├── cog.py, models.py, modals.py, views.py
│   │   ├── service.py, validators.py, embeds.py
│   ├── tournament/                  # Verifica mazzi Artisan
│   │   ├── models.py, validators.py, service.py, embeds.py
│   └── tournament_system/           # Sistema tornei Swiss
│       └── cog.py                   # 14 comandi slash torneo
│
├── services/                        # Business logic layer
│   ├── tournament_service.py        # Orchestratore tornei
│   ├── pairing_engine.py            # Algoritmo pairing Swiss
│   ├── standings.py                 # Classifiche con tiebreaker
│   └── rating.py                    # Sistema rating Glicko-2
│
├── repositories/                    # Data access layer
│   ├── base.py                      # CRUD generico
│   ├── user_repository.py
│   ├── tournament_repository.py
│   └── banlist_repository.py
│
├── database/                        # Database layer
│   ├── engine.py                    # Engine SQLAlchemy, session, migrazioni
│   └── models.py                    # Modelli ORM: User, Tournament, Match, BannedCard
│
├── utils/                           # Moduli di supporto
│   ├── card_cache.py                # Cache persistente carte (JSON)
│   ├── arena_overrides.py           # Override rarità Arena vs Paper
│   ├── deck_image_generator.py      # Generazione immagini mazzo
│   ├── tournament_logic.py          # Utility (barra OMW, label rank)
│   ├── tournament_embeds.py         # Embed builder per tornei
│   └── permissions.py               # Decorator permessi admin
│
├── data/                            # Dati persistenti
│   ├── card_cache.json              # Cache carte Scryfall
│   ├── arena_rarity_data.json       # Override SPG processati
│   ├── clepsydra.db                 # Database SQLite
│   └── cards.txt                    # Banlist formato Artisan (seed)
│
├── assets/                          # Risorse statiche
│   ├── backgrounds/                 # 25 sfondi per gilde/colori MTG
│   └── logo_clepshydra.png          # Watermark per deck image
│
├── legacy/                          # Codice V1 originale (monolitico)
│   ├── legacy_bot.py
│   ├── legacy_presentation.py
│   └── legacy_deck_image_generator.py
│
├── tests/                           # Test suite
│   └── tournament/
│       ├── test_standings.py
│       ├── test_tournament_embeds.py
│       └── test_tournament_logic.py
│
└── docs/                            # Documentazione
    ├── banlist-system.md
    ├── architettura.md
    ├── database.md
    ├── comandi.md
    └── ...
```

---

## 5. Funzionalità Implementate

### 5.1 Sistema Presentazioni

Quando un nuovo utente entra nel server Discord riceve automaticamente il ruolo `Viandante` che limita la visibilità dei canali. Tramite il comando `/presentati` viene avviato un wizard multi-step:

1. **Dati Personali**: Nome, Nickname Arena, Anno di nascita, Professione, Provenienza
2. **Preferenze**: Formati preferiti, Colori, Gilde — validati contro liste predefinite
3. **Dettagli Opzionali**: Risultati, Altre Passioni
4. **Anteprima**: Embed di preview con conferma/cancellazione
5. **Pubblicazione**: Embed nel canale presentazioni, cambio ruolo da `Viandante` a `Planeswalker`

Il sistema valida ogni campo con regex e logica di dominio. Supporta select menu interattivi per colori, gilde e formati.

### 5.2 Verifica Mazzo Artisan

Il comando `/artisan_check_deck` apre un modal dove l'utente incolla la propria decklist. Il sistema esegue:

1. **Parsing** della decklist con supporto al blocco `About` per il nome del mazzo
2. **Check banlist**: se una carta è bannata → stop immediato (nessuna chiamata Scryfall)
3. **Fetch batch** via `POST /cards/collection` (chunk da 75 carte)
4. **Verifica legalità Artisan**: rarità common/uncommon su Arena, escluso `set_type=alchemy`
5. **Conteggio**: mainboard >= 60, sideboard <= 15
6. **Generazione immagine** showcase se il mazzo è valido
7. **Pubblicazione** embed con risultato nel canale dedicato

### 5.3 Generazione Immagini Mazzo

Per ogni mazzo valido viene generata un'immagine PNG che include:

- **Sfondo dinamico** basato sulla gilda/colori del mazzo
- **Griglia delle carte** del mainboard raggruppate per tipo (Creature, Spell, Land)
- **Colonna sideboard** con immagini e lista testuale
- **Header** con nome del mazzo e nickname del giocatore
- **Watermark** logo Clepshydra colorato dinamicamente

### 5.4 Sistema Tornei Swiss

Implementato in V2 con:

- Creazione e gestione tornei con formato Artisan
- Iscrizione con validazione deck automatica
- Pairing Swiss automatico con anti-rematch e bye handling
- Registrazione risultati con game wins
- Classifica con punteggio 3/1/0 e tiebreaker OMW/GWP/OGW
- Rating Glicko-2 aggiornato a fine torneo
- Leaderboard giocatori

### 5.5 Sistema di Logging

Tutti gli eventi rilevanti vengono loggati su un canale Discord dedicato tramite embed colorati:

- **INFO**: Operazioni completate con successo (verifiche ok, torneo avviato)
- **WARN**: Validazioni fallite, carte bannate, campi non validi
- **ERROR**: Errori critici, eccezioni non gestite
- **DEBUG**: Startup del bot, migrazioni DB, sincronizzazione comandi

### 5.6 Override Rarità SPG

Gestisce carte con rarità diversa tra Arena e Paper (es. Special Guest). Il comando `/update_spg_overrides` (admin only) scansiona l'intero set via Scryfall e aggiorna automaticamente `arena_rarity_data.json`.

---

## 6. Sistema di Cache e Dati Persistenti

### 6.1 `card_cache.json`

Cache persistente delle carte Scryfall. Ogni entry contiene i dati base della carta più il campo `artisan_legal` (bool) aggiunto dopo il primo check. Salvataggio ogni 60 secondi con lock asincrono e scrittura atomica (file `.tmp` + `os.replace`).

### 6.2 `arena_rarity_data.json`

Memorizza gli override di rarità per carte con discrepanza Arena/Paper. Include la lista dei set già processati per evitare ri-scansioni.

### 6.3 Database SQLite

Il database principale con tabelle `users`, `tournaments`, `tournament_players`, `matches`, `banned_cards`. Gestito tramite SQLAlchemy 2.0 async con migrazioni automatiche all'avvio.

---

## 7. Interazione con API Esterne

### 7.1 Strategia Scryfall

| Caratteristica | Descrizione |
|---|---|
| Endpoint batch | `POST /cards/collection` — fino a 75 carte per richiesta |
| Endpoint prints | `GET prints_search_uri` filtrato con `game:arena` |
| Rate limiting | Semaforo asyncio + delay 110ms tra richieste |
| Retry logic | Backoff esponenziale su 429, max 5 tentativi |
| Cache | Carta già vista → nessuna chiamata API |
| Alchemy filter | `set_type=alchemy` escluso esplicitamente |

---

## 8. Flusso di una Verifica Mazzo Artisan

```
1. Utente incolla decklist → /artisan_check_deck
2. Parser → estrae nome, carte, mainboard/sideboard
3. Banlist check → O(1) contro set in memoria
4. Scryfall fetch → POST /cards/collection (carte non in cache)
5. Artisan check → override locale → cache disco → cache memoria → GET prints Arena
6. Validazione conteggio → mainboard >= 60, sideboard <= 15
7. Generazione immagine → download carte, compositing, watermark
8. Pubblicazione → embed + immagine su canale dedicato
```

---

## 9. Limitazioni Attuali e Debito Tecnico

### 9.1 Architetturali

- **Cache banlist non invalidata** dopo aggiunta/rimozione via slash command (fix: ricaricare `self._banlist` dopo ogni modifica)
- **Doppia fonte di verità** per la banlist: `ArtisanService._banlist` (cache) vs database
- **Assenza di test** per i moduli core (PairingEngine, TournamentService) — solo test standings e embeds
- **Nessun meccanismo di recovery** per il token Discord (se scade, il bot si ferma)
- **DeckImageGenerator** non testato in ambiente headless (dipende da Pillow)

### 9.2 Operativi

- **Nessun Docker**: deploy manuale tramite SSH
- **Nessun CI/CD**: nessun workflow automatico
- **1 GB RAM**: vincolo che limita scelte tecnologiche (no PostgreSQL, no Redis)

---

## 10. Architettura V2

L'architettura attuale (V2) segue una separazione netta in quattro layer:

```
┌──────────────────────────────────────┐
│      Discord API (Gateway + REST)     │
├──────────────────────────────────────┤
│  COGS (Controller / Presenter)        │
│  - PresentationCog                     │
│  - TournamentCog                       │
│  - TournamentSystemCog                 │
│  - Logger                              │
├──────────────────────────────────────┤
│  SERVICE LAYER (Business Logic)       │
│  - TournamentService (orchestratore)   │
│  - PairingEngine (Swiss algorithm)     │
│  - StandingsCalculator (tiebreaker)    │
│  - Rating (Glicko-2)                   │
│  - ArtisanService (deck validation)    │
│  - PresentationService                 │
├──────────────────────────────────────┤
│  REPOSITORY LAYER (Data Access)       │
│  - UserRepository                      │
│  - TournamentRepository                │
│  - MatchRepository                     │
│  - BanlistRepository                   │
├──────────────────────────────────────┤
│  DATABASE / EXTERNAL APIs             │
│  - SQLite (SQLAlchemy 2.0 + aiosqlite)│
│  - Scryfall API (aiohttp)             │
└──────────────────────────────────────┘
```

### Tournament Architecture

```
TournamentService
├── PairingEngine       → Swiss pairing, anti-rematch, bye
├── StandingsCalculator → 3/1/0 scoring, OMW/GWP/OGW
├── Rating              → Glicko-2 update
└── Match               → Result management
```

---

## 11. Roadmap — ClepshydraBot V2

### Sprint 0 — Git e GitHub *(completato)*
Repository GitHub, primo commit, `.gitignore`, `.env.example`, `LICENSE`.

### Sprint 1 — Refactor Presentazioni *(completato)*
Wizard multi-step con select menu, validatori dedicati, service layer.

### Sprint 2 — Refactor Architetturale *(completato)*
Separazione business logic e UI Discord. Introduzione di `services/`, `repositories/`, `config/`, `models/`.

### Sprint 3 — SQLite *(completato)*
SQLAlchemy async + aiosqlite. Modelli: User, Tournament, TournamentPlayer, Match, BannedCard.

### Sprint 4 — Sistema Tornei Swiss *(completato)*
Iscrizione, pairing automatico, risultati, classifiche, rating Glicko-2.

### Sprint 5 — Banlist *(completato)*
Migrazione da txt a tabella SQLite. Comandi slash per gestione.

### Sprint 6 — Documentazione *(completato)*
README professionale, documentazione tecnica, CHANGELOG.

### Sprint 7 — Docker *(da fare)*
Dockerfile multi-stage, docker-compose con volume per data/.

### Sprint 8 — CI/CD *(da fare)*
GitHub Actions: lint (ruff), test (pytest), build check.
