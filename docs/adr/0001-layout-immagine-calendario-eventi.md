# ADR-0001 — Layout dell'immagine calendario Event Schedule

**Stato:** accettato (3.2.0) — spostato qui da `CLAUDE.md` il 2026-10-20

## Contesto

`send_event_schedule_log()` (`utils/arena_event_schedule.py`) deve rendere leggibile su Discord la
sezione "Full Event Calendar" delle pagine Wizards: decine di voci per categoria (Premier Draft, Quick
Draft, Sealed, eventi Metagame...), molte delle quali durano settimane e si sovrappongono.

## Decisione

Un'immagine per mese (`EventCalendarImageGenerator` in `utils/event_calendar_image_generator.py`), in due
parti:

1. **Gantt con una riga per categoria**, colorata per *famiglia* (Premier Draft / Quick Draft / Flashback /
   Sealed & Cube / Metagame / Community). La famiglia è un'euristica sulle parole chiave del nome categoria
   (`_classify_family()`), non un dato della pagina Wizards.
2. **Elenco testuale dettagliato** sotto il Gantt: nomi completi degli eventi, senza troncamento, con la
   categoria tra parentesi.

`_clean_name()` rimuove i prefissi ridondanti `"Magic: The Gathering | "` e `"Arena Direct for "`, perché
il colore della riga comunica già la categoria. Un range che attraversa un confine di mese viene spezzato
in un segmento per mese (`build_month_calendar()`). L'anno mancante viene dedotto dalla data corrente
(`_infer_start_year()`): se il mese di inizio è più di circa 6 mesi "indietro" rispetto al mese corrente,
si assume l'anno successivo (pagina pubblicata a fine anno che cita gennaio).

## Alternative scartate (iterazioni su dati reali)

- **Griglia a giorni**: illeggibile, perché le categorie lunghe si ripetono identiche in decine di celle.
- **Gantt con una riga per famiglia** (6 righe): si perde l'informazione "sono due code distinte o la
  stessa disegnata due volte?".
- **Embed testuale con un campo per categoria** (prima della 3.2.0): troppo lungo e senza visione d'insieme.

## Conseguenze

- Nessuna categoria viene fusa con altre; i nomi che non entrano in una barra stretta restano leggibili
  nell'elenco sotto il Gantt.
- `create_month_panel()` (Gantt per categoria senza famiglie) e `create_multi_month_calendar()` (più
  mesi in un'unica immagine con un elenco unico) restano nel modulo, non usati, nel caso si voglia tornare
  a quei layout.
- Se le categorie vengono lette ma nessuna voce ha date riconoscibili, non si genera un'immagine vuota:
  viene loggato un `WARN` `ARENA_EVENT_SCHEDULE_NO_DATES`, solo nel canale log.
