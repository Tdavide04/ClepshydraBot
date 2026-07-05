# Sistema Presentazioni

## Panoramica

Il sistema di presentazione gestisce il censimento e la verifica degli utenti all'ingresso nel server Discord. Automatizza l'assegnazione dei ruoli e pubblica embed di presentazione sul canale dedicato.

---

## Struttura del Modulo

```
cogs/presentation/
├── __init__.py          # Esporta PresentationCog
├── cog.py               # Comando /presentati + listener on_member_join
├── models.py            # PresentationData (dataclass)
├── modals.py            # BasicPresentationModal + OptionalPresentationModal
├── views.py             # Select menu + Preview View
├── service.py           # PresentationService (pubblica, ruoli)
├── validators.py        # Validazione input (regex + logica di dominio)
└── embeds.py            # Builder embed preview/pubblicazione
```

---

## Flusso di Presentazione

### 1. Ingresso Utente (`cog.py:12-35`)

All'arrivo di un nuovo membro:
- Assegna ruolo `Viandante` (configurabile via `INITIAL_ROLE` in `.env`)
- Invia messaggio di benvenuto in DM o canale designato
- Invita a usare `/presentati` per completare la verifica

### 2. Avvio Wizard (`cog.py:45-70`)

Il comando `/presentati` è disponibile a tutti. Se l'utente ha già il ruolo `FINAL_ROLE` (`Planeswalker`), il comando viene rifiutato con un messaggio esplicativo.

Il wizard multi-step procede in 4 fasi:

#### Fase 1 — Modale Base (`modals.py:12-52`)
`BasicPresentationModal` con 5 campi obbligatori:

| Campo | Tipo | Validazione |
|---|---|---|
| Nome | TextInput | Regex: lettere, spazi, apostrofi, trattini (2-100 char) |
| Nickname Arena | TextInput | Regex: alfanumerico, underscore, trattini (2-100 char) |
| Anno di nascita | TextInput | Regex: 4 cifre, range 1900-2010 |
| Professione | TextInput | Regex: lettere, spazi, apostrofi (2-100 char) |
| Provenienza | TextInput | Regex: lettere, spazi, apostrofi (2-100 char) |

#### Fase 2 — Select Menu (`views.py:15-90`)
`PreferencesView` con 4 select menu a scelta multipla:

| Menu | Opzioni |
|---|---|
| Colori preferiti | Bianco, Blu, Nero, Rosso, Verde (max 5) |
| Gilde preferite | Tutte le 10 gilde di Ravnica (max 10) |
| Formati Costruiti | Standard, Pioneer, Modern, Legacy, Vintage, Artisan, Brawl, Historic, Explorer, Timeless (max 10) |
| Formati Limitati | Draft, Sealed, Cube (max 3) |

#### Fase 3 — Modale Opzionale (`modals.py:54-88`)
`OptionalPresentationModal` con 4 campi opzionali:

| Campo | Descrizione |
|---|---|
| Anno inizio Magic cartaceo | Minimo 1993 |
| Anno inizio MTGA | Minimo 2017 |
| Risultati | Tornei vinti, piazzamenti, record |
| Altre Passioni | Interessi extra-Magic |

#### Fase 4 — Anteprima e Conferma (`views.py:92-140`)

`PreviewView` mostra un embed riassuntivo con:
- Tutti i dati inseriti organizzati per sezioni
- Bottoni **Conferma** e **Annulla**

---

## Validazione (`validators.py`)

Ogni campo viene validato tramite funzioni dedicate:

| Funzione | Validazione |
|---|---|
| `validate_name(value)` | Regex: solo lettere, spazi, apostrofi, trattini; 2-100 caratteri |
| `validate_years(value)` | 4 cifre, range 1900-2010 per nascita; Magic ≥ 1993, MTGA ≥ 2017 |
| `validate_colors(values)` | Max 5, solo valori validi (WUBRG) |
| `validate_guilds(values)` | Max 10, solo gilde valide |
| `validate_formats(values)` | Formati costruiti: 10 valori; limitati: 3 valori |
| `validate_text(value, allow_empty)` | Testo libero con lunghezza controllata |

In caso di errori, viene restituito un messaggio con:
- Campi mancanti (in ordine alfabetico)
- Campi con valori non validi (in ordine alfabetico)
- Messaggio di errore specifico per ogni campo

---

## Pubblicazione (`service.py`)

`PresentationService.publish()`:
1. Converte `PresentationData` in embed tramite `build_published_embed()`
2. Invia l'embed sul canale `PRESENTATION_CHANNEL_ID`
3. Rimuove ruolo `INITIAL_ROLE` (`Viandante`)
4. Assegna ruolo `FINAL_ROLE` (`Planeswalker`)
5. Elimina il messaggio di interazione originale
6. Logga l'evento (INFO)

---

## Embed (`embeds.py`)

### `build_preview_embed(data)`
Usata per l'anteprima, mostra tutti i dati in forma compatta.

### `build_published_embed(data)`
Usata per la pubblicazione finale, con:
- Header: nome utente + nickname Arena
- Sezioni: Personale, Magic, Preferenze, Risultati, Passioni
- Colore: personalizzato per utente
- Footer: timestamp di pubblicazione
