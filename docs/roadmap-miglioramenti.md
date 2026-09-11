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

**Stato:** fatto (2026-09-11)

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

**Validazione:** `pytest tests/ -v` — 88 test, tutti passano (`test_tournament_service.py` esercita
`_migrate_schema()` ad ogni test tramite `init_db()`, ma solo nel caso "colonne già presenti", perché il
DB di test viene creato da zero con `Base.metadata.create_all`). Per verificare anche il percorso reale
— schema vecchio senza le colonne, `ALTER TABLE` effettivo, poi idempotenza alla riesecuzione — ho creato
a mano un DB SQLite con lo schema "vecchio" (tabelle senza le colonne migrate) tramite uno script
temporaneo, eseguito `_migrate_schema()` due volte di fila: la prima aggiunge tutte le 8 colonne
(confermato leggendo `PRAGMA table_info` per ogni tabella dopo), la seconda non genera errori né
ALTER ridondanti. Script rimosso dopo la verifica, non è nel repository.

---

## Step 3 — Invalidazione/TTL per `artisan_legal` nella cache carte

**Stato:** fatto (2026-09-11)

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

**Implementazione effettiva:** TTL di 30 giorni (`ARTISAN_LEGAL_TTL_DAYS`), timestamp salvato come ISO
8601 UTC (`artisan_legal_checked_at`). Entry cacheate prima di questa modifica non hanno il campo →
trattate come scadute (fail-open verso il ricontrollo, non verso la fiducia illimitata). Aggiunto anche
`/invalidate_card_cache <carta>` (admin, in `cogs/spg_override_updater.py` insieme a
`/update_spg_overrides`) per correggere singole carte senza aspettare il TTL — rimuove l'intera entry,
non solo il flag, quindi rifà anche il fetch dei dati base. La cache in-memoria per processo
(`_ARENA_LEGAL_CACHE`, keyed su `oracle_id`) **non** è soggetta a TTL: si azzera comunque ad ogni riavvio
del bot, quindi il rischio di staleness lì è minore e resta fuori scope per questo step.

**Validazione:** `pytest tests/ -v` — 88/88 verdi (nessun test esistente copre `card_cache.py` o
`ArtisanService`, invariato). Ho scritto ed eseguito uno script manuale temporaneo (rimosso dopo il
check, non è nel repository) che verifica: entry senza timestamp → stale; entry fresca appena marcata →
non stale; entry oltre 30 giorni → stale; entry entro 30 giorni → non stale; timestamp malformato →
stale (fail-open); `invalidate_card()` rimuove una entry esistente e ritorna `False` se già assente.

---

## Step 4 — Card cache: da JSON a tabella SQLite

**Stato:** fatto (2026-09-11)

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

**Implementazione effettiva (design discusso prima di scrivere codice, vedi conversazione):** invece di
rendere l'intera cache `async` (avrebbe richiesto propagare `await` in ~15 punti di
`cogs/deck_validation/service.py`), solo il livello di persistenza è cambiato:
- `get_cached_card()`/`set_cached_card()` restano **sincrone**, operano sul dict `_card_cache` in
  memoria esattamente come prima — zero modifiche al percorso caldo di `validate_deck()`.
- `save_cache()` traccia `_dirty_upserts`/`_dirty_deletes` (due `set[str]` di nomi carta) invece di un
  flag booleano globale, e scrive su SQLite solo le entry cambiate (UPSERT/DELETE mirati), non l'intero
  dizionario.
- `load_cache()` è diventata `async` e si è spostata da "chiamata in `ArtisanService.__init__()`" (una
  volta per istanza, quindi in teoria più volte per processo) a "chiamata una tantum in
  `database/engine.py:init_db()`", accanto a `_migrate_banlist()`/`_migrate_schema()` — il caricamento
  cache è un concern di avvio bot, non di istanza del service.
- Migrazione una tantum: se `cached_cards` è vuota e `data/card_cache.json` esiste ancora, `load_cache()`
  importa tutto in un'unica transazione.
- `data/card_cache.json` rimosso dal tracking git (`git rm --cached`) e aggiunto a `.gitignore`; resta
  sul disco locale come file inerte (non più letto né scritto dal bot una volta popolata la tabella).
- `periodic_save_loop()` invariata nella forma (chiama ancora `save_cache()` ogni 60s), cambia solo cosa
  fa `save_cache()` internamente.

**Validazione:** `python -m pytest tests/ -v` — 101/101 verdi (93 → 101, +8 nuovi test diretti su
`utils/card_cache.py` in `tests/deck_validation/test_card_cache.py`: caricamento a tabella vuota,
migrazione legacy, upsert incrementale, no-op senza modifiche, update di una riga esistente,
invalidazione con delete al salvataggio successivo, invalidazione di una entry mai persistita
(nessun errore), reload dopo un "restart" simulato). In più, verifica manuale mirata contro il vero
`data/card_cache.json` del repository (407 entry, 2.2MB, incluse carte double-faced): migrazione
completa, dati identici byte-per-byte su un campione, nessuna riga duplicata su un secondo "riavvio"
simulato — script temporaneo, rimosso dopo il check, non è nel repository.

---

## Step 5 — Ridurre query N+1 in `TournamentService._update_ratings`

**Stato:** fatto (2026-09-11)

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

**Validazione:** `pytest tests/ -v` — 88/88 test verdi, incluso
`test_tournament_completes_and_updates_rating` che esercita `_update_ratings()` end-to-end contro SQLite
reale (non solo un compile-check). `docs/tornei.md` non descrive il dettaglio implementativo di
`_update_ratings()` (solo il nome nella tabella dei metodi), quindi non necessitava aggiornamento.

---

## Step 6 — Uniformare la gestione delle sessioni DB

**Stato:** fatto (2026-09-11)

**Problema:** ogni metodo di `TournamentService` (e delle altre classi service) ripete manualmente
`session, repo... = self._get_repos()` seguito da `try/finally: await session.close()`. Corretto ma
verboso e facile da dimenticare in nuovi metodi.

**Modifiche:**
- `services/tournament_service.py` (ed eventuali altri service con lo stesso pattern): introdurre un
  context manager (`async with self._session() as (repo1, repo2, ...):`) che centralizza apertura/chiusura
  sessione, senza cambiare la logica di business dei singoli metodi.

**Documentazione da aggiornare:**
- `CHANGELOG.md` — nuova voce `Refactored`.
- `docs/architettura.md` e `CLAUDE.md` non descrivevano `_get_repos()` nel dettaglio: nessuna modifica
  necessaria.

**Validazione:** `pytest tests/ -v` — 88/88 verdi. `test_tournament_service.py` esercita quasi tutti i
metodi pubblici di `TournamentService` (registrazione, avvio, pairing, submit risultato, round
successivo, drop forzato, standings, rating), quindi ha fatto da rete di sicurezza reale per il refactor,
non solo un compile-check. Diff verificato a mano riga per riga: ogni metodo converte
`session, repo... = self._get_repos(); try: ...; finally: await session.close()` in
`async with self._repos() as (session, repo, ...): ...` senza toccare la logica al suo interno.

---

## Step 7 — Test per `ArtisanService` (completare la copertura deck validation)

**Stato:** fatto (2026-09-11) — `TournamentService` già coperto (vedi "Punto di partenza")

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

**Implementazione effettiva:** `tests/deck_validation/test_artisan_service.py` (+ `conftest.py` con lo
stesso seeding env var di `tests/tournament/conftest.py`, duplicato deliberatamente per restare
eseguibile in isolamento). Niente `pytest-asyncio`: stesso pattern `asyncio.run()` già in uso.
`ArtisanService._post_with_retry`/`_get_with_retry` sono sostituiti per-istanza con funzioni async finte
(nessuna chiamata di rete reale, nessun mock library). 5 test:
- carta bannata → stop prima di qualunque chiamata Scryfall (verificato passando un `_post_with_retry`
  che solleverebbe `KeyError` se venisse invocato).
- deck valido (mainboard common + sideboard uncommon) → `is_valid` True.
- carta rara → `illegal_rarity_cards` popolato, `is_valid` False.
- **regressione Step 1**: due `ArtisanService` separate (come nel bot reale), banlist modificata tramite
  la prima, verificata tramite la seconda — cattura esattamente il bug che il fix del 9 settembre aveva
  lasciato aperto.
- **regressione Step 3**: entry di cache "legacy" (senza `artisan_legal_checked_at`) con
  `artisan_legal=True`, ma la ristampa via API risulta ora rara → deve essere ri-verificata, non presa
  per buona.

**Validazione:** `python -m pytest tests/ -v` — 93/93 verdi (88 preesistenti + 5 nuovi), eseguiti sia come
`tests/deck_validation` in isolamento sia come parte della suite completa.

---

## Step 8 — CI leggero (lint + test)

**Stato:** fatto (2026-09-11) — parziale fin dal "Punto di partenza", chiuso definitivamente qui

**Problema residuo:** `ruff` gira solo come step informativo/non bloccante (`continue-on-error: true` in
`.github/workflows/ci.yml`), perché il codebase ha ~55 problemi di lint pre-esistenti non ancora sanati.

**Modifiche (per chiudere lo step):**
- Sistemare i problemi di lint pre-esistenti (import inutilizzati, statement multipli su una riga, ecc.)
  in un intervento dedicato, fuori scope dagli step funzionali sopra.
- Rimuovere `continue-on-error: true` dal job `lint` in `.github/workflows/ci.yml` una volta pulito.

**Documentazione da aggiornare:**
- `docs/infrastruttura.md` — sezione "Roadmap Infrastrutturale", Sprint 8: da "parziale" a "completato".
- `CHANGELOG.md` — nuova voce `Fixed`.

**Implementazione effettiva:** 54 problemi (42 fuori da `legacy/`, che è stato escluso in `ruff.toml`
invece di essere corretto — vedi CLAUDE.md "Legacy code": non fa parte del codice attivamente
mantenuto). 27 corretti con `ruff check . --fix` (import inutilizzati, f-string senza placeholder,
import multipli sulla stessa riga) — diff rivisto a mano prima di fidarsi dell'autofix. I restanti 15
manuali:
- 12 `E701` (statement multipli su una riga) → separati su righe distinte, nessun cambio di logica.
- 2 `E712` (`TournamentPlayer.dropped == False` in `repositories/tournament_repository.py`) → **non**
  applicato il fix suggerito da ruff (`not TournamentPlayer.dropped`), che per un'espressione di query
  SQLAlchemy avrebbe un significato diverso da quello inteso; usato invece `.is_(False)`, l'idioma
  SQLAlchemy corretto per lo stesso filtro (gestisce anche i NULL correttamente, a differenza di `==`).

Rimosso `continue-on-error: true` dal job `lint` in `.github/workflows/ci.yml`: ora blocca la CI come
`pytest`.

**Validazione:** `ruff check .` → `All checks passed!`. `pytest tests/ -v` → 108/108 verdi, invariato
rispetto a prima del lint cleanup (nessuna delle correzioni ha toccato la logica).

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

Step 0 → 1 → 2 → 5 → 6 → 3 → 7 → 4 (tutti fatti) → 8 (chiusura lint, da fare) → 9 (da fare).

Motivazione: prima i fix di correttezza a basso rischio e isolati (2, 5), poi i refactor interni senza
cambi di comportamento visibile (6) — entrambi appoggiati alla suite `test_tournament_service.py` già
esistente. Poi l'invalidazione TTL (3), che non tocca lo schema. Lo Step 7 (test `ArtisanService`) viene
completato subito prima dello Step 4, così la migrazione della cache carte a SQLite — il cambiamento più
invasivo dell'elenco — può essere validata con test reali. La chiusura del gate `ruff` (8) e Docker (9)
chiudono la lista: non correggono debito applicativo, riducono il rischio operativo futuro.
