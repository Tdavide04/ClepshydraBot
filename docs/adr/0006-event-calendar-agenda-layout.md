# ADR-0006 — Event Schedule calendar image: an agenda, not a Gantt

**Status:** accepted (4.1.0). Supersedes [ADR-0001](0001-event-calendar-image-layout.md).

## Context

The 3.2.0 image (ADR-0001) was a Gantt with one row per Wizards category and a text list below. Looking at
four real months (November 2026 – February 2027) it had these problems:

- Row labels were cut ("Flashback Premier Dra…") or overflowed the chart ("November Format: Magic: The
  Gathering | Star Trek Sealed").
- A day column is 32 px wide, so a 1–3 day event showed "Qualif…", "Artisa…". The real name lived only in the
  list, which repeated every bar and made the image about twice as tall as the chart.
- The same event listed under four categories ("Star Trek" in Premier, Pick-Two, Traditional and Contender
  Draft) took four rows and four list lines.
- Light text on light bars, no weekdays, week lines on days 1, 8, 15… instead of Mondays, a navy background.
- The text was 12 px on a 1230 px wide image: unreadable once Discord shrinks it on a phone.

The maintainer's first reaction to a mock-up that moved long titles outside their bar was that the title must not
move. That ruled out every layout that puts the name inside the bar and falls back on placing it next to it.

## Decision

An **agenda**, one image per month, 900 px wide and as tall as needed (`EventCalendarImageGenerator` in
`features/monitors/calendar_image.py`):

- **Four groups** with a header and a color each: Limited, Constructed, Metagame, Eventi vari. Rows are sorted
  by start day, then end day, then name.
- **One row per event**: exact dates and weekdays on the left ("10 – 30", "mar → lun"), the full name (up to 3
  lines, wrapped, never moved) and its Wizards categories in the middle, and a strip of day ticks on the right
  that marks the days covered, with weekends tinted.
- **Same event, same dates, several categories → one row** carrying all the categories.
- **Neutral warm background, no blue.** Group colors keep at least 4.5:1 contrast on it.
- The pure logic (grouping, cleaning, merging, ordering) lives in `features/monitors/calendar_model.py`, with no
  Pillow and no `config`, so it is tested without drawing anything.

The group is a keyword heuristic (`classify_event()`), not data from the Wizards page, which only gives a
category such as "Midweek Magic" or "Other Events" that hosts events of any format:

1. A category with "metagame", "arena direct", "format:" or "championship" → Metagame.
2. A category with "flashback", "draft", "sealed" or "cube" → Limited.
3. Otherwise the event name decides: draft/sealed/cube → Limited; standard, historic, pioneer, pauper, brawl,
   artisan, gladiator, explorer, timeless, alchemy → Constructed.
4. Anything else → Eventi vari. These names are listed in a console `WARN`, so a new format gets noticed
   instead of silently landing in the wrong group.

There is no "today" marker: the image is posted when the Wizards page changes, not every day, so a marker would
be wrong a few hours later.

## Rejected alternatives

Four other proposals were drawn on the same November data and compared (research notes: agenda views test best
on phones, month grids are an overview, long labels belong in a column, bars need 3:1 and text 4.5:1 contrast):

- **Gantt with the names in a fixed left column and unlabeled bars.** Closest to the old look and good on a
  desktop, but 1166 px wide: the text shrinks on a phone.
- **Half-month Gantt with the name inside the bar (wrapped, up to 3 lines).** Everything in one place, but long
  names on short bars are cut ("On the Edge with Magic: The Gatheri…") and the categories vanish on narrow bars.
- **Classic month grid with bars crossing the days.** The familiar look, but the long events repeat in every
  week, the image is the tallest, and the group sections and categories are lost.
- **Overview strip plus agenda.** The agenda's readability plus a Gantt at a glance, at the cost of a longer
  image and a strip where a bar can't be matched to its event without reading below.
- From ADR-0001, still rejected: a day grid, and a Gantt with one row per family.
- **Five refinements of the old Gantt** (row per category, names in bars, list below), drawn on September 2026
  after the agenda was implemented: minimal touch-up, two-line names, numbered badges that point to the list,
  grouped sections, and a 1700 px wide panorama. They fix the labels, weekdays and contrast, but every one is
  1250–1700 px wide, so on a phone the inline preview shrinks the text, and short bars still cut long names or
  need a number to find them in the list. The maintainer kept the agenda.

## Consequences

- No event name is truncated or moved, and every exact date is in the image. The text list is gone.
- The image is taller than a Gantt for the same month (a dense month such as December 2026 is about 2100 px
  high). Discord shrinks inline images and publishes no limits for it, so the image is meant to be opened full
  size on a phone. Whether the inline preview is acceptable was not measured on a real client when this was
  written.
- `create_month_panel()`, `create_multi_month_calendar()` and the family classification of ADR-0001 are gone;
  nothing called them.
- The keyword lists in `calendar_model` need a manual touch when Wizards introduces a new format.
- Fonts: `arial.ttf` first, then DejaVu and Liberation. On the Linux VM the layout is measured with whichever is
  found, so a font with different metrics only changes where lines wrap.
