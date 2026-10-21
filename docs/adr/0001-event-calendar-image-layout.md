# ADR-0001 — Event Schedule calendar image layout

**Status:** accepted (3.2.0) — moved here from `CLAUDE.md` on 2026-10-20

## Context

`send_event_schedule_log()` (`features/monitors/event_schedule.py`) has to make the "Full Event Calendar" section of
the Wizards pages readable on Discord: dozens of entries per category (Premier Draft, Quick Draft, Sealed,
Metagame events...), many of which last weeks and overlap.

## Decision

One image per month (`EventCalendarImageGenerator` in `features/monitors/calendar_image.py`), in two
parts:

1. **A Gantt with one row per category**, colored by *family* (Premier Draft / Quick Draft / Flashback /
   Sealed & Cube / Metagame / Community). The family is a keyword heuristic on the category name
   (`_classify_family()`), not data from the Wizards page.
2. **A detailed text list** below the Gantt: full event names, no truncation, with the category in
   parentheses.

`_clean_name()` strips the redundant `"Magic: The Gathering | "` and `"Arena Direct for "` prefixes, because
the row's color already conveys the category. A range crossing a month boundary is split into one segment per
month (`build_month_calendar()`). The missing year is inferred from the current date
(`_infer_start_year()`): if the start month is more than about 6 months "behind" the current month, it is taken
as next year (a page published at year end that mentions January).

## Rejected alternatives (iterations on real data)

- **Day grid**: unreadable, because long-running categories repeat identically across dozens of cells.
- **Gantt with one row per family** (6 rows): loses the "are these two distinct queues or the same one drawn
  twice?" information.
- **Text embed with one field per category** (before 3.2.0): too long and with no overview.

## Consequences

- No category is merged with another; names that don't fit in a narrow bar stay readable in the list below
  the Gantt.
- `create_month_panel()` (per-category Gantt without families) and `create_multi_month_calendar()` (several
  months in a single image with one shared list) stay in the module, unused, in case those layouts are wanted
  again.
- If the categories are parsed but no entry has a recognizable date, no empty image is generated: a `WARN`
  `ARENA_EVENT_SCHEDULE_NO_DATES` is logged, in the log channel only.
