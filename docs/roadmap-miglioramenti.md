# Roadmap — Miglioramenti Tecnici

Piano di lavoro per correggere i bug noti e migliorare l'efficienza/robustezza del bot, emerso da una
revisione completa della codebase (Settembre 2026). Non sostituisce la roadmap funzionale storica in
`CHANGELOG.md` — copre solo debito tecnico e miglioramenti architetturali.

## Punto di partenza (già presente su `feature/v2` prima di questa roadmap)

Un intervento precedente (9 settembre 2026, commit `bedcbe9`/`f46f1de`/`9f4203e`) aveva già affrontato
parte di questo stesso debito, in parallelo alla stesura di questa roadmap:

- **CI**: `.github/workflows/ci.yml` — `pytest` come gate bloccante su ogni push/PR, `ruff` come step
  informativo (non bloccante: il codebase ha debito di lint pre-esistente non ancora sanato). Copre lo
  Step 8 qui sotto.
- **Test `TournamentService`**: `tests/tournament/test_tournament_service.py`, 10 test end-to-end
  (iscrizione, avvio, pairing, submit risultato, round successivo, drop forzato, standings, rating) su
  SQLite isolato per test, senza mock — con un pattern `asyncio.run()` per test invece di
  `pytest-asyncio` (vedi `tests/tournament/conftest.py`). Copre gran parte dello Step 7.
- **Resilienza avvio**: `main.py` intercetta `discord.LoginFailure` e altre eccezioni di startup, logga
  su stderr con prefisso `FATAL:` ed esce con codice non-zero invece di fallire in modo silenzioso.
  `deploy/clepshydrabot.service` (systemd) è disponibile come alternativa, ma **non è quello in uso in
  produzione** — la VM usa `pm2` (vedi `docs/infrastruttura.md`).
- Un primo tentativo di fix per la cache banlist (`ArtisanService.reload_banlist()`), **incompleto**:
  reload solo sull'istanza chiamata, non sulla seconda `ArtisanService` istanziata da
  `cogs/deck_validation/__init__.py`. Completato nello Step 1 qui sotto (cache spostata a livello di
  modulo).

## Regola per ogni step

Ogni step, quando implementato, **deve**:

1. Modificare solo il codice indicato in "Modifiche" (nessun refactor opportunistico fuori scope).
2. Aggiornare tutti i documenti elencati in "Documentazione da aggiornare" — inclusi quelli il cui
   contenuto diventa **obsoleto** (es. una sezione "Problemi Noti" che descrive un bug ora risolto va
   rimossa o marcata come risolta, non lasciata a mentire).
3. Aggiornare `README.md` se lo step cambia qualcosa di visibile lì (comandi, quick start, stack,
   struttura repository).
4. Aggiungere una voce in `CHANGELOG.md` (nuova versione, semver: fix → patch, feature/refactor → minor)
   nello stesso formato già in uso (sezioni `Added`/`Fixed`/`Changed`/`Refactored`/`Docs`).
5. Aggiornare `CLAUDE.md` solo se cambia un'informazione che vi è descritta (comandi, layering,
   comportamento di un componente citato).
6. Essere validato: eseguire `pytest tests/ -v` (o `python -m pytest`), e se lo step tocca codice non
   coperto da test, spiegare esplicitamente come è stato verificato manualmente (non affermare che
   "funziona" senza prova).
7. Lavorare su `feature/v2`, non su `main` — `main` riceve solo merge via PR di `feature/v2`.

Stato di ogni step: `da fare` → `in corso` → `fatto`.

---

## Step 0 — Refactor `docs/ClepshydraBot_Resoconto_Tecnico.md`

**Stato:** fatto (2026-09-11)

**Problema:** il documento duplicava quasi integralmente `docs/infrastruttura.md` (infra, deployment,
env, logging) e altri doc dedicati (architettura, funzionalità, cache, flusso validazione), diventando
una seconda fonte di verità da tenere sincronizzata a mano.

**Modifiche:** ridotto alle sole informazioni di "scheda anagrafica" non duplicate altrove: istanza OCI
(OCID, data avvio, IP, accesso SSH, process manager), specifiche hardware/OS, stack tecnologico e
versioni, richiamo al vincolo RAM. Rimosse le sezioni Struttura Repository, Funzionalità, Cache, API
Esterne, Flusso Validazione, Limitazioni/Debito Tecnico, Architettura V2, Roadmap — sostituite da una
tabella di rimandi ai documenti dedicati, incluso questo file.

**Documentazione aggiornata:** `docs/ClepshydraBot_Resoconto_Tecnico.md` (questo step).

---

## Step 1 — Fix invalidazione cache banlist

**Stato:** fatto (2026-09-11)

**Problema:** `ArtisanService._banlist` (`cogs/deck_validation/service.py`) era caricata una volta dal DB
e — nel codice di partenza (prima di qualunque fix) — mai ricaricata. Un primo tentativo di fix
(`reload_banlist()`, vedi sopra) restava comunque incompleto: il bot crea **due** istanze separate di
`ArtisanService` (`cogs/tournament_system/cog.py` e `cogs/deck_validation/__init__.py`), e ricaricare
l'attributo `self._banlist` su una non ha effetto sull'altra.

**Modifiche:**
- `cogs/deck_validation/service.py`: `_banlist` spostata da attributo di istanza a variabile di modulo
  `_banlist_cache`, condivisa da tutte le `ArtisanService`. Nuova funzione di modulo
  `invalidate_banlist_cache()` (stesso pattern già usato da `utils/arena_overrides.py` per
  `_override_cache`). Il metodo `reload_banlist()` resta come wrapper d'istanza (nessuna modifica ai
  call site in `cogs/tournament_system/cog.py`), ma ora invalida la cache condivisa invece che solo il
  proprio attributo.

**Documentazione aggiornata:**
- `docs/banlist-system.md` — §5, §10, "Problemi Noti" punto 2.
- `docs/caching.md` — §4 "Cache Banlist", tabella "Riepilogo Cache".
- `CHANGELOG.md`.

**Validazione:** `pytest tests/ -v` — 88 test, tutti passano. Nessun test automatico copre ancora il
percorso banlist/DB con due istanze di `ArtisanService` in parallelo (previsto come estensione dello
Step 7). Verificato a mano leggendo il flusso: entrambi i cog istanziano `ArtisanService(bot)` in
`__init__`, e da questa modifica entrambe le istanze leggono/scrivono la stessa `_banlist_cache` di
modulo — un'invalidazione chiamata da una qualsiasi delle due è visibile all'altra al prossimo
`validate_deck()`.

---

## Step 2 — Gestione esplicita delle migrazioni schema

**Stato:** da fare

**Problema:** `database/engine.py:_migrate_schema()` avvolge ogni `ALTER TABLE` in
`try/except Exception: pass` (8 occorrenze). Il pattern è voluto per il caso "colonna già esistente", ma
nasconde anche errori reali (permessi, disco pieno, tipo colonna errato) senza log.

**Modifiche:**
- `database/engine.py`: prima di ogni `ALTER TABLE`, verificare l'esistenza della colonna con
  `PRAGMA table_info(<tabella>)` invece di affidarsi all'eccezione; loggare a `WARN`/`ERROR` (via Logger
  cog o stdout) qualunque eccezione imprevista invece di ignorarla silenziosamente.
- Rimuovere il doppio `import os` duplicato in cima al file (righe 1-2).

**Documentazione da aggiornare:**
- `docs/database.md` — sezione sulle migrazioni: descrivere il nuovo controllo esplicito.
- `CHANGELOG.md` — nuova voce `Fixed`/`Changed`.

---

## Step 3 — Invalidazione/TTL per `artisan_legal` nella cache carte

**Stato:** da fare

**Problema:** il campo `artisan_legal` in `data/card_cache.json` (`utils/card_cache.py`) non scade mai.
Se una carta diventa legale/illegale in Artisan dopo una nuova stampa Arena, il bot continuerà a usare
il valore calcolato al primo check, senza alcun modo di correggerlo se non editando il JSON a mano.

**Modifiche:**
- `utils/card_cache.py`: aggiungere un timestamp per entry (es. `checked_at`) e un TTL configurabile
  (proposta: 30 giorni) oltre il quale `_is_arena_artisan_legal()` (in
  `cogs/deck_validation/service.py`) ri-verifica la carta invece di fidarsi della cache.
- Valutare un comando admin di invalidazione mirata (`/invalidate_card_cache <carta>`), analogo a
  `/update_spg_overrides`, per correggere singole carte senza attendere il TTL.

**Documentazione da aggiornare:**
- `docs/caching.md` — sezione "Cache Carte Scryfall": aggiungere TTL e nuovo comando.
- `docs/deck-validation.md` — punto 4 "Verifica Legalità Arena": aggiornare l'ordine dei controlli.
- `docs/comandi.md` — se aggiunto il nuovo comando admin.
- `CHANGELOG.md` — nuova voce `Added`/`Fixed`.

---

## Step 4 — Card cache: da JSON a tabella SQLite

**Stato:** da fare

**Problema:** `save_cache()` riscrive per intero `data/card_cache.json` ogni 60s se `_dirty`, anche per
una sola carta modificata. La cache cresce senza pulizia (nessun limite di dimensione) — su una VM da
1 GB RAM, il rewrite completo periodico di un file sempre più grande è I/O e memoria sprecati rispetto a
una scrittura incrementale. Il file è inoltre già tracciato in git (2.2 MB, cresciuto per 8 commit senza
alcun valore storico) — da valutare se rimuoverlo dal tracking indipendentemente da questo step.

**Modifiche:**
- `database/models.py`: nuovo modello `CachedCard` (o simile) nella stessa istanza SQLite già in uso.
- `utils/card_cache.py`: sostituire il backend JSON con query SQLAlchemy (get/set incrementali); rimuovere
  `periodic_save_loop()` se non più necessario (le scritture diventano dirette).
- `main.py`: rimuovere l'avvio del task se eliminato.
- Migrazione una tantum dei dati esistenti da `data/card_cache.json` alla nuova tabella, poi il file può
  essere eliminato da `data/` e rimosso dal tracking git.

**Documentazione da aggiornare:**
- `docs/caching.md` — riscrivere interamente la sezione "Cache Carte Scryfall".
- `docs/database.md` — aggiungere la nuova tabella allo schema.
- `docs/architettura.md` — diagramma architetturale (rimuovere `card_cache.json` come storage separato).
- `CLAUDE.md` — sezione utils/caching.
- `CHANGELOG.md` — nuova voce `Changed`/`Refactored`.

**Nota:** step a rischio più alto degli altri (tocca lo schema DB e un componente usato da ogni
validazione deck) — farlo dopo lo Step 7 (test `ArtisanService`), non prima, per validarlo con test reali
invece che a occhio.

---

## Step 5 — Ridurre query N+1 in `TournamentService._update_ratings`

**Stato:** da fare

**Problema:** `services/tournament_service.py:_update_ratings()` carica ogni `User` con un
`session.get(User, tp.user_id)` separato dentro un ciclo sui giocatori, invece di una singola query
batch. Impatto oggi trascurabile (tornei da poche decine di persone), ma non scala.

**Modifiche:**
- `services/tournament_service.py`: sostituire il loop di `session.get` con una singola query
  `select(User).where(User.id.in_(user_ids))`.

**Documentazione da aggiornare:**
- `docs/tornei.md` — se descrive il flusso di aggiornamento rating, aggiornare il riferimento
  all'implementazione.
- `CHANGELOG.md` — nuova voce `Changed` (performance).

**Nota:** `tests/tournament/test_tournament_service.py` copre già `_update_ratings()` end-to-end — questo
step può appoggiarsi a quella suite invece di scriverne una nuova da zero.

---

## Step 6 — Uniformare la gestione delle sessioni DB

**Stato:** da fare

**Problema:** ogni metodo di `TournamentService` (e delle altre classi service) ripete manualmente
`session, repo... = self._get_repos()` seguito da `try/finally: await session.close()`. Corretto ma
verboso e facile da dimenticare in nuovi metodi.

**Modifiche:**
- `services/tournament_service.py` (ed eventuali altri service con lo stesso pattern): introdurre un
  context manager (`async with self._session() as (repo1, repo2, ...):`) che centralizza apertura/chiusura
  sessione, senza cambiare la logica di business dei singoli metodi.

**Documentazione da aggiornare:**
- `docs/architettura.md` — pattern "Dependency Injection" / gestione sessione, se descritto.
- `CLAUDE.md` — se descrive il pattern `_get_repos()`.
- `CHANGELOG.md` — nuova voce `Refactored`.

**Nota:** anche qui, `test_tournament_service.py` fa da rete di sicurezza per verificare che il refactor
non cambi comportamento.

---

## Step 7 — Test per `ArtisanService` (completare la copertura deck validation)

**Stato:** in corso — `TournamentService` già coperto (vedi "Punto di partenza"), manca `ArtisanService`

**Problema:** `ArtisanService.validate_deck()` — banlist + fetch Scryfall + rarità Artisan + override SPG
— non ha copertura, a differenza di `TournamentService` che ora ha 10 test end-to-end.

**Modifiche:**
- `tests/deck_validation/test_artisan_service.py`: test con client Scryfall mockato (no chiamate di rete
  reali) per `validate_deck()`, seguendo lo stesso approccio già in uso in
  `tests/tournament/test_tournament_service.py` (DB SQLite isolato per test via fixture, nessuna nuova
  dipendenza — niente `pytest-asyncio`, si riusa il pattern `asyncio.run()` di
  `tests/tournament/test_tournament_service.py`).
- Aggiungere un test dedicato all'invalidazione della cache banlist su due istanze separate di
  `ArtisanService` (il bug corretto nello Step 1), per evitare regressioni silenziose.

**Documentazione da aggiornare:**
- `CLAUDE.md` — sezione "Commands" (nuovo percorso di test), se cambia qualcosa di rilevante.
- `CHANGELOG.md` — nuova voce `Added` con conteggio test.

---

## Step 8 — CI leggero (lint + test)

**Stato:** fatto (parziale) — vedi "Punto di partenza"

**Problema residuo:** `ruff` gira solo come step informativo/non bloccante (`continue-on-error: true` in
`.github/workflows/ci.yml`), perché il codebase ha ~55 problemi di lint pre-esistenti non ancora sanati.

**Modifiche (per chiudere lo step):**
- Sistemare i problemi di lint pre-esistenti (import inutilizzati, statement multipli su una riga, ecc.)
  in un intervento dedicato, fuori scope dagli step funzionali sopra.
- Rimuovere `continue-on-error: true` dal job `lint` in `.github/workflows/ci.yml` una volta pulito.

**Documentazione da aggiornare:**
- `docs/infrastruttura.md` — sezione "Roadmap Infrastrutturale", Sprint 8: da "parziale" a "completato".
- `CHANGELOG.md` — nuova voce `Fixed`.

---

## Step 9 — Containerizzazione (Docker)

**Stato:** da fare

**Problema:** deploy tramite `pm2` su SSH manuale, nessuna riproducibilità dell'ambiente.

**Modifiche:**
- `Dockerfile` multi-stage basato su `python:3.12-slim`.
- `docker-compose.yml` con volume persistente per `data/`, `restart: unless-stopped`, `.env` montato.

**Documentazione da aggiornare:**
- `docs/infrastruttura.md` — sezione "Roadmap Infrastrutturale", Sprint 7 → completato; sezione
  "Deployment" con le istruzioni Docker come opzione aggiuntiva (senza sostituire la sezione `pm2`, che
  resta il metodo effettivamente in uso finché non si decide di migrare).
- `README.md` — "Quick Start" con opzione Docker.
- `CHANGELOG.md` — nuova voce `Added`.

---

## Ordine consigliato

Step 0 (fatto) → 1 (fatto) → 2 → 5 → 6 → 3 → 7 → 4 → 8 (chiusura lint) → 9.

Motivazione: prima i fix di correttezza a basso rischio e isolati (2, 5), poi i refactor interni senza
cambi di comportamento visibile (6) — entrambi appoggiati alla suite `test_tournament_service.py` già
esistente. Poi l'invalidazione TTL (3), che non tocca lo schema. Lo Step 7 (test `ArtisanService`) viene
completato subito prima dello Step 4, così la migrazione della cache carte a SQLite — il cambiamento più
invasivo dell'elenco — può essere validata con test reali. La chiusura del gate `ruff` (8) e Docker (9)
chiudono la lista: non correggono debito applicativo, riducono il rischio operativo futuro.
