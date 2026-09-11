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
              │  • Persistita su SQLite (tabella cached_cards) │
              │    con UPSERT/DELETE incrementali, non su un   │
              │    JSON riscritto per intero ogni volta        │
              │  • artisan_legal field già calcolato (con TTL) │
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

Fino a Settembre 2026 la cache era persistita su `data/card_cache.json`, riscritto per intero ogni 60
secondi se qualcosa era cambiato — anche per una singola carta modificata su migliaia. Il file era
inoltre tracciato in git, crescendo senza pulizia ad ogni commit (2.2MB, zero valore come storico
versionato). Dalla migrazione (Step 4 di `docs/roadmap-miglioramenti.md`), la cache vive nella tabella
SQLite `cached_cards` (`database/models.py:CachedCard`), con scritture incrementali (UPSERT/DELETE solo
sulle entry cambiate). `data/card_cache.json` non è più tracciato in git (resta come file locale inerte,
utile solo per la migrazione una tantum descritta sotto) e non viene più scritto dal bot.

### Funzioni

| Funzione | Descrizione |
|---|---|
| `load_cache()` (async) | Carica `cached_cards` in `_card_cache`; se la tabella è vuota e `data/card_cache.json` esiste ancora, migra il JSON legacy una tantum |
| `save_cache()` (async) | UPSERT/DELETE solo delle entry in `_dirty_upserts`/`_dirty_deletes`, non l'intera cache |
| `get_cached_card(name)` | Restituisce dati Scryfall di una carta o `None` (legge solo `_card_cache`, sincrono) |
| `set_cached_card(name, data)` | Aggiunge/aggiorna carta in memoria; la segna per il prossimo `save_cache()` |
| `mark_artisan_legal(name, entry, legal)` | Imposta `artisan_legal` + `artisan_legal_checked_at` e salva la entry |
| `is_artisan_legal_stale(entry)` | `True` se manca il timestamp o è oltre `ARTISAN_LEGAL_TTL_DAYS` (30 giorni) |
| `invalidate_card(name)` | Rimuove una carta dalla cache, in memoria e (al prossimo save) dal DB (usato da `/invalidate_card_cache`) |
| `periodic_save_loop(delay=60)` | Task asincrono che chiama `save_cache()` ogni 60s |

### Dettagli Implementativi

- `_dirty_upserts` / `_dirty_deletes`: due `set[str]` di nomi carta invece di un flag booleano globale —
  `save_cache()` sa esattamente quali righe scrivere/cancellare, senza toccare quelle invariate
- `_save_lock`: `asyncio.Lock()` per prevenire race-condition su scritture concorrenti
- `_loaded`: flag che garantisce un solo caricamento per avvio del bot; `load_cache()` viene chiamata da
  `database/engine.py:init_db()` (non più da `ArtisanService.__init__()` — il caricamento è un concern di
  avvio, non di istanza del service)
- Import di `database`/`database.models` **locali alle funzioni** (non a livello di modulo) per evitare
  un import circolare: `database/engine.py` chiama `card_cache.load_cache()`, che a sua volta ha bisogno
  di `database.get_session` — stesso pattern già usato da `database/engine.py:_migrate_banlist()` per
  `repositories.banlist_repository`

### Migrazione da JSON a SQLite

Se all'avvio la tabella `cached_cards` è vuota e `data/card_cache.json` esiste ancora, `load_cache()`
importa tutte le entry nel DB in un'unica transazione e stampa `Cache carte: migrate N entry da
data/card_cache.json a SQLite`. Da quel momento il file JSON non viene più letto né scritto — verificato
manualmente contro il file reale del repository (407 entry, incluse carte double-faced): migrazione
completa, dati identici byte-per-byte, nessuna riga duplicata su un secondo "riavvio" simulato.

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

### Struttura (tabella `cached_cards`)

| Colonna | Tipo | Descrizione |
|---|---|---|
| `card_name` | String(200), PK | Nome carta lowercase — stesso key format del vecchio JSON |
| `data` | Text | L'intero dizionario Scryfall (dati base + `artisan_legal` + `artisan_legal_checked_at`) serializzato come JSON |

Un unico blob JSON per riga invece di colonne dedicate per `artisan_legal`/`cmc`/ecc.: nessuna query SQL
li filtra oggi, e tenerli come blob evita di duplicare la forma variabile dei dati Scryfall (le carte
double-faced hanno `card_faces` invece di `image_uris` diretto) in due posti. Contenuto tipico del blob
per `"lightning bolt"`:

```json
{
  "name": "Lightning Bolt",
  "type_line": "Instant",
  "cmc": 1.0,
  "image_uris": { "small": "https://...", "normal": "https://..." },
  "prints_search_uri": "https://api.scryfall.com/cards/search?q=...",
  "artisan_legal": true,
  "artisan_legal_checked_at": "2026-09-11T12:00:00+00:00"
}
```

---

## 2. Override Rarità SPG (`utils/arena_overrides.py`)

### Problema

Carte del set **SPG (Special Guests)** stampate su carta a rarità common/uncommon, ma apparse su Arena solo a rarità rare/mythic. Scryfall le vedrebbe come illegali per Artisan, ma dovrebbero essere legali in base alla rarità paper più bassa.

`SPG` non è un set che esce una volta e si chiude: Scryfall usa un unico set code che cresce nel tempo — nuove Special Guests vengono aggiunte con quasi ogni nuovo set principale (~4-8 settimane in media).

### Soluzione

Dizionario di override che forza una rarità più bassa per queste carte, aggiornato **automaticamente ogni settimana** da un task in background (`periodic_spg_refresh_loop()`, avviato da `main.py` insieme a `periodic_save_loop()`), oltre che manualmente via `/forced_rarity_refresh` (admin).

| Funzione | Descrizione |
|---|---|
| `get_override_rarity(card_name)` | Restituisce `"common"`, `"uncommon"` o `None` |
| `update_spg_overrides(set_code="spg")` | Scansiona solo le carte **non ancora valutate** del set, aggiorna JSON — incrementale, sicuro da chiamare ripetutamente |
| `_fetch_prints_by_oracle_ids(session, oracle_ids)` | Recupera le stampe di più carte in una query combinata (`oracleid:X or oracleid:Y or ...`, paginata), a gruppi di `_PRINTS_BATCH_SIZE` (25) invece di una `prints_search_uri` per carta |
| `periodic_spg_refresh_loop(bot)` | Task in background: chiama `update_spg_overrides()` ogni 7 giorni (primo giro subito all'avvio), logga su Discord se trova qualcosa di nuovo |
| `invalidate_override_cache()` | Forza ricarica del JSON al prossimo accesso |

### Cache In-Memory

`_override_cache`: variabile globale popolata al primo accesso, invalidabile esplicitamente. `_update_lock`
(`asyncio.Lock()`) evita che il task automatico e un `/forced_rarity_refresh` manuale sovrascrivano il
JSON contemporaneamente se capitano nello stesso momento.

### Batching delle richieste Scryfall

Fino a Settembre 2026 `update_spg_overrides()` faceva una richiesta `prints_search_uri` per OGNI carta non
ancora valutata (pattern N+1) — innocuo per i run incrementali settimanali (poche carte nuove), ma il
primo run dopo la migrazione da `processed_sets` a `checked_cards` deve ricontrollare l'intero set in un
colpo solo: osservato in produzione, ~175 carte da valutare hanno prodotto decine di risposte 429
consecutive, ogni scan rallentato dal backoff esponenziale (`_scryfall_get`).

Sostituito con `_fetch_prints_by_oracle_ids()`: raggruppa le carte non valutate in blocchi di 25
(`_PRINTS_BATCH_SIZE`) e recupera le stampe di tutto il blocco con un'unica query combinata
(`q=oracleid:X or oracleid:Y or ...&unique=prints`, paginata se il blocco produce più risultati di una
pagina). 175 carte: da 175 richieste individuali a 7 batch, da ~diversi minuti (con retry su 429) a ~12
secondi, verificato dal vivo contro Scryfall.

**Deduplicazione obbligatoria, non solo ottimizzazione**: la ricerca `set:spg unique=prints` a monte
elenca una riga per **stampa**, non per carta — una carta con più stampe SPG appare più volte, quindi
l'elenco di `oracle_id` da raggruppare contiene sempre duplicati. Verificato dal vivo che una query
Scryfall con termini `oracleid:` ripetuti (`oracleid:X or oracleid:X`) restituisce risultati
**incompleti** (alcune carte mancanti dal risultato, senza errore esplicito) invece di un errore o di un
risultato corretto — `_fetch_prints_by_oracle_ids()` deduplica sempre la lista prima di costruire la
query (`list(dict.fromkeys(oracle_ids))`).

Un batch fallito (query Scryfall senza risposta valida) non segna nessuna delle sue carte come
controllata — vengono ritentate tutte insieme al prossimo giro, stesso principio di "non perdere una
carta per sempre" già in uso per i singoli fallimenti prima del redesign.

### Struttura JSON (`data/arena_rarity_data.json`)

```json
{
  "overrides": {
    "Swords to Plowshares": "uncommon",
    "Lightning Bolt": "common",
    "Sylvan Library": "uncommon"
  },
  "checked_cards": {
    "SPG": ["Swords to Plowshares", "Lightning Bolt", "Sylvan Library", "..."]
  }
}
```

`checked_cards[set_code]` elenca **ogni** carta già valutata in quel set, con o senza override aggiunto
(non solo quelle che ne hanno ottenuto uno). Una nuova scansione salta solo le carte già presenti qui —
i giri successivi al primo costano solo le carte apparse dall'ultimo controllo, non l'intero set.

**Storia**: fino a Settembre 2026 il campo era `processed_sets: ["SPG"]`, un flag "tutto il set fatto per
sempre" — corretto per un set che esce una volta, sbagliato per uno che cresce nel tempo. Dopo la prima
scansione riuscita, ogni run successivo (anche manuale) diventava un no-op permanente, senza modo di
sbloccarlo se non editando il JSON a mano. Un file nel vecchio formato non blocca più nulla: viene
semplicemente trattato come "nessuna carta ancora controllata" e riscansionato una volta per intero.

---

## 3. Monitoraggio Event Schedule Arena (`utils/arena_event_schedule.py`)

### Problema

Wizards pubblica una pagina dedicata "**[Set] MTG Arena Event Schedule**" (URL tipo
`magic.wizards.com/en/news/mtg-arena/the-hobbit-event-schedule`) una volta per espansione — non
settimanalmente come i post "MTG Arena Announcements". Contiene una sezione "Full Event Calendar" con la
rotazione Quick Draft e tutti gli altri eventi ricorrenti, organizzata per categoria. Non esiste
un'API/RSS ufficiale per sapere quando una nuova pagina viene pubblicata o quando una esistente viene
aggiornata (Wizards la modifica **in place** durante il ciclo di vita del set, non solo alla
pubblicazione).

### Soluzione

`magic.wizards.com/en/sitemap.xml` è un sitemap XML standard con `<lastmod>` per ogni pagina del sito.
Un task in background scarica quotidianamente il sitemap (richiesta economica, file statico), filtra le
URL `*-event-schedule` sotto `/en/news/mtg-arena/` e individua quella con il `lastmod` **più recente** —
il set attualmente attivo. Wizards non rimuove dal sitemap le pagine dei set passati: senza questo filtro,
a un dato momento il sitemap ne contiene sempre diverse (osservato in produzione: 4 pagine
contemporaneamente), e la prima esecuzione su una macchina con stato vuoto le segnalerebbe tutte come
"nuove" in un colpo solo, producendo un flood di notifiche per eventi ormai conclusi. Solo se quella più
recente è nuova o ha un `lastmod` cambiato rispetto allo stato salvato viene scaricata e interpretata la
pagina vera e propria (fetch + parsing HTML, più costoso e fragile) — la maggior parte dei check
giornalieri non fa nulla oltre alla GET sul sitemap, perché il contenuto reale cambia solo ogni 6-9
settimane.

| Funzione | Descrizione |
|---|---|
| `check_event_schedule_updates(force=False)` | Individua la pagina più recente sul sitemap; se nuova/cambiata (o sempre, se `force=True`) la scarica+interpreta; ritorna `[]` o `[{url, lastmod, categories}]` |
| `_pick_latest(entries)` | Tra le pagine trovate, seleziona quella col `lastmod` più alto (confronto lessicografico su timestamp ISO-8601 a larghezza fissa) |
| `parse_full_event_calendar(html)` | Estrae `{categoria: [voci]}` dalla sezione "Full Event Calendar"; `None` se la sezione non viene trovata (drift strutturale del sito) |
| `periodic_event_schedule_check_loop(bot)` | Task in background: chiama `check_event_schedule_updates()` ogni 24 ore (primo giro subito all'avvio), logga su Discord se la pagina più recente è nuova/aggiornata |

### Parsing e gestione dei fallimenti

La sezione "Full Event Calendar" di queste pagine è HTML realmente strutturato (non prosa libera come i
post Announcements settimanali): blocchi `<h2>/<h3>/<h4>Categoria</h2>` seguiti da
`<ul><li>intervallo date: descrizione</li></ul>`, delimitati tra l'heading "Full Event Calendar" e la
prima chiusura `</article>` successiva (esclude le card di navigazione laterale, che usano heading con
attributi CSS anziché bare come quelli della sezione calendario).

Se la struttura attesa non viene trovata, `parse_full_event_calendar()` ritorna `None` invece di un
riassunto parziale o sbagliato — il chiamante logga un `WARN` ("controllo manuale consigliato") invece di
postare dati potenzialmente inaffidabili come se fossero autorevoli. Un fetch di rete fallito (pagina non
raggiungibile) non aggiorna lo stato salvato: viene ritentato al giro successivo invece di essere marcato
come "già visto".

### Stato (`data/arena_event_schedule_state.json`, non tracciato in git)

```json
{
  "latest_url": "https://magic.wizards.com/en/news/mtg-arena/the-hobbit-event-schedule",
  "latest_lastmod": "2026-09-02T16:05:08.364Z"
}
```

Traccia solo l'ultima pagina (più recente) effettivamente processata, non l'intero storico — puro
bookkeeping operativo, a differenza di `arena_rarity_data.json` non contiene dati curati/editoriali,
quindi non è tracciato in git (vedi `.gitignore`).

Comando admin per forzare un controllo immediato (ignora il confronto `lastmod`, ricontrolla comunque la
pagina più recente sul sitemap): `/forced_event_schedule_check`.

---

## 4. Scryfall API — Strategia

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

## 5. Cache Banlist

La banlist (`BannedCard` in SQLite) è cacheata in memoria nella variabile di modulo
`_banlist_cache: set[str] | None` in `cogs/deck_validation/service.py`, condivisa da tutte le istanze
di `ArtisanService`.

| Aspetto | Dettaglio |
|---|---|
| Caricamento | Prima validazione dopo l'avvio (o dopo un'invalidazione): `await BanlistRepository.get_all_for_format()`, poi espansa con `_expand_double_faced()` (aggiunge la sola metà fronte delle carte double-faced — vedi `docs/banlist-system.md` "Problemi Noti") |
| Validità | Fino alla prossima invalidazione esplicita |
| Invalida | `ArtisanService.reload_banlist()` (wrapper su `invalidate_banlist_cache()`), chiamato da `/banlist_aggiungi` e `/banlist_rimuovi` subito dopo la scrittura sul DB — l'effetto è visibile da tutte le istanze, non solo da quella su cui è chiamato |

---

## Riepilogo Cache

| Cache | Location | Persistenza | Invalidation |
|---|---|---|---|
| Carte Scryfall | Tabella SQLite `cached_cards` | 60s, incrementale (solo entry cambiate) | `artisan_legal` con TTL 30gg; `/invalidate_card_cache` per singola carta |
| Override rarità | `arena_rarity_data.json` | Su aggiornamento | Esplicita (`invalidate_override_cache()`) |
| Event Schedule Arena | `arena_event_schedule_state.json` | Check giornaliero (parsing solo su `lastmod` cambiato) | `/forced_event_schedule_check` (ignora `lastmod`) |
| Banlist | `_banlist_cache` (modulo) | Condivisa tra istanze | Esplicita (`reload_banlist()` dopo add/remove) |
