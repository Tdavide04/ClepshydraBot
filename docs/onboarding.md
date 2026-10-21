# Onboarding (Presentations)

## Overview

The presentation system registers and verifies users when they join the Discord server. It automates role
assignment and publishes a presentation embed to the dedicated channel.

Field labels and menu options below are quoted as users see them in Discord, in Italian.

---

## Module Structure

```
cogs/presentation/
├── __init__.py          # Exports PresentationCog
├── cog.py               # /presentati command + on_member_join and on_message listeners
├── models.py            # PresentationData (dataclass) + PRESENTATION_DATA_STORE
├── modals.py            # BasicPresentationModal + OptionalPresentationModal
├── views.py             # Select menus + PreferencesView + PreviewView
├── service.py           # PresentationService (validation, publishing, roles)
├── validators.py        # valida_* functions
└── embeds.py            # Preview/publication embed builders
```

---

## Presentation Flow

### 1. User Joins (`PresentationCog.on_member_join()` in `cog.py`)

When a new member arrives:
- Assigns the `Viandante` role (configurable via `INITIAL_ROLE` in `.env`)
- Posts a welcome message in the presentation channel (deleted after 30 minutes), inviting them to use
  `/presentati` to complete verification

Any other message posted in the presentation channel is deleted (`on_message`), with a short reminder to use
`/presentati` and an INFO `MESSAGE_DELETE` log.

### 2. Wizard Start (`PresentationCog.presentati()` in `cog.py`)

The `/presentati` command is available to everyone, in a server only. If the user already has the
`FINAL_ROLE` role (`Planeswalker`), the command is refused.

The multi-step wizard goes through 4 phases.

#### Phase 1 — Basic Modal (`BasicPresentationModal` in `modals.py`)
Modal "Presentazione Clepshydra" with 5 required text fields:

| Field (UI label) | Length |
|---|---|
| Nome | 2-100 |
| Nickname Arena | 2-50 |
| Anno di nascita (birth year) | exactly 4 |
| Professione (profession) | 2-100 |
| Provenienza (hometown) | 2-100 |

#### Phase 2 — Select Menus (`PreferencesView` and the `*Select` classes in `views.py`)
`PreferencesView` with multiple-choice select menus, each allowing from 0 up to all of its options:

| Menu | Options |
|---|---|
| Colors | Bianco, Nero, Rosso, Blu, Verde, Incolore, Tutti, N/A |
| Guilds | The 10 Ravnica guilds, the 10 three-color shards/wedges, Tutte, N/A |
| Constructed formats | Standard, Pioneer, Modern, Legacy, Vintage, Explorer, Historic, Alchemy, Timeless, Pauper, Penny, Artisan, Nessuno |
| Limited/other formats | Draft, Sealed, Limited, Block / Blocco, Centurion, Commander, Oathbreaker, Brawl, Extended, Two-Headed Giant, Conspiracy, Planechase, Archenemy, Momir, Kitchen Table, Nessuno |

#### Phase 3 — Details Modal (`OptionalPresentationModal` in `modals.py`)
Modal "Dettagli Opzionali" with 4 fields:

| Field (UI label) | Required | Notes |
|---|---|---|
| Anno inizio Magic Cartaceo | yes | Year they started paper Magic, or "mai"/"N/A" |
| Anno inizio MTG Arena | yes | Year they started MTG Arena, or "mai"/"N/A" |
| Risultati in Magic (opzionale) | no | Results: tournaments, placements |
| Altre Passioni (opzionale) | no | Interests outside Magic |

#### Phase 4 — Preview and Confirmation (`PreviewView` in `views.py`)

`PreviewView` shows the presentation embed as it will be published, with confirm and cancel buttons.

- **Conferma** calls `PresentationService.publish()` and sends the member the `message` of the
  `ServiceResult` it returns. The buttons stay usable after a refusal (`ok=False`) and lock after a
  publication. An unexpected exception isn't caught here: it reaches `ReportingView.on_error`, which shows
  the generic error message and logs `INTERACTION_ERROR` for staff.
- **Annulla** replaces the preview with "Presentazione annullata." (no embed, no buttons) and discards the
  member's data from `PRESENTATION_DATA_STORE`, so the next `/presentati` starts from scratch.

The data between steps lives only in `PRESENTATION_DATA_STORE`, an in-memory dict: a bot restart in the
middle of a presentation loses it, and the member has to run `/presentati` again.

---

## Validation (`validators.py`)

`valida_presentazione(data)` runs the checks below and returns `(missing, errors)`, where `errors` lists the
UI labels of the invalid fields. Required text fields are enforced by the modal itself, so `missing` is
always empty today.

| Function | Rule |
|---|---|
| `valida_anno_nascita(anno)` | 4 digits, after 1900, before the current year, and age ≥ 16 |
| `valida_anno_cartaceo(anno)` | "mai"/"n/a", or a year from 1993 to the current year |
| `valida_anno_arena(anno)` | "mai"/"n/a", or a year from 2017 to the current year |
| `valida_formati(formati)` | Every value in the constructed or limited sets (`VALIDI_formati_*`); anything containing "block"/"blocco" is accepted |
| `valida_colori(colori)` | Every value, after `normalizza_colore()`, in `VALIDI_colori` |
| `valida_gilde(gilde)` | Every value, after `normalizza_gilda()`, in `VALIDI_gilde` |

An empty selection is valid for colors, guilds and formats.

---

## Publication (`service.py`)

`PresentationService.publish()` returns a `ServiceResult` (`core/results.py`) and never replies to the
member itself: the caller sends `message`. `ok=False` means nothing was posted and no role changed.
1. Validates the data (`valida_presentazione()`): on invalid fields it logs WARN
   `PRESENTATION_VALIDATION_FAILED` and returns `ok=False` with the list of fields to fix
2. Converts `PresentationData` into an embed via `build_published_embed()`
3. Sends the embed to the `PRESENTATION_CHANNEL_ID` channel. If the channel isn't found it logs ERROR
   `PRESENTATION_CHANNEL_MISSING` and returns `ok=False` with a message saying staff were notified
4. Removes the `INITIAL_ROLE` role (`Viandante`) and assigns the `FINAL_ROLE` role (`Planeswalker`)
5. Logs INFO `PRESENTATION_COMPLETED` with a link to the published message
6. Removes the user's data from the temporary `PRESENTATION_DATA_STORE`
7. Returns `ok=True` with "✅ Benvenuto tra i Planeswalker!"

---

## Embeds (`embeds.py`)

### `build_preview_embed(member, data)`
Used both for the preview and, through `build_published_embed()`, for the final publication — the two are
the same embed. Green, with a timestamp, the member's avatar as thumbnail, and fields "Dati Personali",
"Inizio Magic", "Preferenze", plus "Risultati" and "Altre Passioni" only when filled in.

### `build_published_embed(member, data)`
Delegates to `build_preview_embed()`.

`build_message_content(data)` (a plain-text version in the V1 style) is still in the module but nothing
calls it.
