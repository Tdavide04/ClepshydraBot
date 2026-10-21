# Caching and External APIs

## Overview

ClepshydraBot calls the **Scryfall API** to validate Artisan decks. To minimize HTTP calls and respect rate
limits, it implements a three-level caching system. It also watches two kinds of Wizards pages through the
`magic.wizards.com` sitemap (sections 3 and 3b).

---

## Cache Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Card request                              │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Level 1: Rarity overrides (arena_overrides.py)               │
│  • In-memory cache (_override_cache)                          │
│  • arena_rarity_data.json (persistent)                        │
│  • Only for SPG / cards with an Arena-paper mismatch          │
└────────────────────────┬─────────────────────────────────────┘
                         │
                    ┌────┴────┐
                    ▼         ▼ (no override found)
              RETURN        CONTINUE
              (legal)           │
                                ▼
              ┌────────────────────────────────────────────────┐
              │  Level 2: Scryfall cache (card_cache.py)       │
              │  • In-memory cache (_card_cache dict)          │
              │  • Persisted to SQLite (cached_cards table)    │
              │    with incremental UPSERT/DELETE, not to a    │
              │    JSON rewritten in full every time           │
              │  • artisan_legal field already computed (TTL)  │
              └──────────────────┬─────────────────────────────┘
                                 │
                            ┌────┴────┐
                            ▼         ▼ (cache miss)
                      RETURN        CONTINUE
                      (legal/            │
                       illegal)          ▼
                      ┌────────────────────────────────────────┐
                      │  Level 3: live Scryfall API            │
                      │  • POST /cards/collection (batch 75)   │
                      │  • GET prints_search_uri + game:arena  │
                      │  • Rate limiting + retry               │
                      │  • Result stored in cache              │
                      └────────────────────────────────────────┘
```

---

## 1. Scryfall Card Cache (`utils/card_cache.py`)

Until September 2026 the cache was persisted to `data/card_cache.json`, rewritten in full every 60 seconds if
anything had changed — even for a single modified card out of thousands. The file was also tracked in git,
growing with no cleanup on every commit (2.2MB, zero value as versioned history). Since the migration (Step 4
of `docs/roadmap.md`), the cache lives in the SQLite table `cached_cards` (`database/models.py:CachedCard`),
with incremental writes (UPSERT/DELETE on the changed entries only). `data/card_cache.json` is no longer
tracked in git (it stays as an inert local file, useful only for the one-off migration described below) and
the bot no longer writes it.

### Functions

| Function | Description |
|---|---|
| `load_cache()` (async) | Loads `cached_cards` into `_card_cache`; if the table is empty and `data/card_cache.json` still exists, migrates the legacy JSON once |
| `save_cache()` (async) | UPSERT/DELETE of the entries in `_dirty_upserts`/`_dirty_deletes` only, not the whole cache |
| `get_cached_card(name)` | Returns a card's Scryfall data or `None` (reads `_card_cache` only, synchronous) |
| `set_cached_card(name, data)` | Adds/updates a card in memory; marks it for the next `save_cache()` |
| `mark_artisan_legal(name, entry, legal)` | Sets `artisan_legal` + `artisan_legal_checked_at` and stores the entry |
| `is_artisan_legal_stale(entry)` | `True` if the timestamp is missing or older than `ARTISAN_LEGAL_TTL_DAYS` (30 days) |
| `invalidate_card(name)` | Removes a card from the cache, in memory and (on the next save) from the DB (used by `/invalidate_card_cache`) |
| `periodic_save_loop(interval_seconds=60)` | Async task calling `save_cache()` every 60s. A failure (e.g. a locked DB) is logged to the console (`[CARD CACHE] save failed, retrying in 60s: ...`) and the loop goes on: the changes stay in `_dirty_upserts`/`_dirty_deletes` (cleared only after a successful commit) and are retried on the next run. Until 3.6.0 a single failure silently killed the task until restart. When the bot shuts down (`ClepshydraBotte.close()` in `main.py`, e.g. `pm2 restart`), `save_cache()` is called one last time before `close_db()`, so the last minute of changes isn't lost |

### Implementation Details

- `_dirty_upserts` / `_dirty_deletes`: two `set[str]` of card names instead of a global boolean flag —
  `save_cache()` knows exactly which rows to write/delete, without touching the unchanged ones
- `_save_lock`: `asyncio.Lock()` to prevent race conditions on concurrent writes
- `_loaded`: flag guaranteeing a single load per bot start; `load_cache()` is called by
  `database/engine.py:init_db()` (no longer by `ArtisanService.__init__()` — loading is a startup concern,
  not a per-service-instance one)
- `database`/`database.models` are imported **inside the functions** (not at module level) to avoid a
  circular import: `database/engine.py` calls `card_cache.load_cache()`, which in turn needs
  `database.get_session` — the same pattern `database/engine.py:_migrate_banlist()` already uses for
  `repositories.banlist_repository`

### Migration from JSON to SQLite

If at startup the `cached_cards` table is empty and `data/card_cache.json` still exists, `load_cache()`
imports every entry into the DB in a single transaction and prints `Card cache: migrated N entries from
data/card_cache.json to SQLite`. From then on the JSON file is neither read nor written — verified by hand
against the repository's real file (407 entries, double-faced cards included): complete migration, data
identical byte for byte, no duplicate rows on a second simulated "restart".

### TTL on `artisan_legal`

The `artisan_legal` flag is no longer considered valid forever. Every time `_is_arena_artisan_legal()`
(`cogs/deck_validation/service.py`) computes it, it calls `mark_artisan_legal()`, which also stores
`artisan_legal_checked_at` (ISO timestamp, UTC). On the next check, if the cached entry's
`artisan_legal_checked_at` is older than `ARTISAN_LEGAL_TTL_DAYS` (30 days) or missing altogether (entry
cached before the TTL existed), the flag counts as stale and the card is re-checked against Scryfall instead
of blindly trusting the cache — covers a card whose Artisan legality changes after a new Arena printing.

To fix a single card without waiting for the TTL, an admin can use `/invalidate_card_cache <carta>`, which
removes the whole entry (not just `artisan_legal`): the next validation also re-fetches the base data from
Scryfall.

### Structure (`cached_cards` table)

| Column | Type | Description |
|---|---|---|
| `card_name` | String(200), PK | Lowercase card name — the same key format as the old JSON |
| `data` | Text | The whole Scryfall dict (base data + `artisan_legal` + `artisan_legal_checked_at`) serialized as JSON |

A single JSON blob per row instead of dedicated columns for `artisan_legal`/`cmc`/etc.: no SQL query filters
on them today, and a blob avoids duplicating the variable shape of Scryfall data (double-faced cards have
`card_faces` instead of a direct `image_uris`) in two places. Typical blob content for `"lightning bolt"`:

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

## 2. SPG Rarity Overrides (`utils/arena_overrides.py`)

### Problem

Cards of the **SPG (Special Guests)** set printed on paper at common/uncommon rarity, but shown on Arena only
at rare/mythic. Scryfall would see them as illegal for Artisan, but they should be legal based on their lowest
paper rarity.

`SPG` isn't a set that comes out once and closes: Scryfall uses a single set code that grows over time — new
Special Guests are added with almost every new main set (~4-8 weeks on average).

### Solution

A dictionary of overrides forcing a lower rarity for these cards, refreshed **automatically every week** by a
background task (`periodic_spg_refresh_loop()`, started by `main.py` together with `periodic_save_loop()`), and
by hand via `/forced_rarity_refresh` (admin).

| Function | Description |
|---|---|
| `get_override_rarity(card_name)` | Returns `"common"`, `"uncommon"` or `None` |
| `update_spg_overrides(set_code="spg")` | Scans only the set's cards **not evaluated yet**, updates the JSON — incremental, safe to call repeatedly |
| `_fetch_prints_by_oracle_ids(session, oracle_ids)` | Fetches the printings of several cards in one combined query (`oracleid:X or oracleid:Y or ...`, paginated), in groups of `_PRINTS_BATCH_SIZE` (25) instead of one `prints_search_uri` per card |
| `periodic_spg_refresh_loop(bot)` | Background task: calls `update_spg_overrides()` every 7 days (first run right at startup), logs to Discord if it finds anything new |
| `invalidate_override_cache()` | Forces the JSON to be reloaded on the next access |

### In-Memory Cache

`_override_cache`: global variable filled on first access, explicitly invalidatable. `_update_lock`
(`asyncio.Lock()`) keeps the automatic task and a manual `/forced_rarity_refresh` from overwriting the JSON at
the same time if they coincide. The JSON is written atomically with `save_json_state()` (`.tmp` +
`os.replace`, the same helper the monitors use): a failure mid-write leaves the previous file intact. Until
3.6.6 it was written in place with `open(..., "w")`, so an interrupted write left a truncated JSON that broke
`json.load` on the next start.

### Batching the Scryfall Requests

Until September 2026 `update_spg_overrides()` made one `prints_search_uri` request for EVERY card not evaluated
yet (N+1 pattern) — harmless for the weekly incremental runs (few new cards), but the first run after the
`processed_sets` → `checked_cards` migration has to re-check the whole set at once: observed in production,
~175 cards to evaluate produced dozens of consecutive 429 responses, every scan slowed down by exponential
backoff (`_scryfall_get`).

Replaced by `_fetch_prints_by_oracle_ids()`: it groups the unevaluated cards into blocks of 25
(`_PRINTS_BATCH_SIZE`) and fetches the whole block's printings with one combined query
(`q=oracleid:X or oracleid:Y or ...&unique=prints`, paginated if the block yields more than one page). 175
cards: from 175 individual requests to 7 batches, from several minutes (with 429 retries) to ~12 seconds,
verified live against Scryfall.

**Deduplication is required, not just an optimization**: the upstream `set:spg unique=prints` search lists one
row per **printing**, not per card — a card with several SPG printings appears more than once, so the list of
`oracle_id`s to group always contains duplicates. Verified live that a Scryfall query with repeated
`oracleid:` terms (`oracleid:X or oracleid:X`) returns **incomplete** results (some cards missing, with no
explicit error) instead of an error or a correct result — `_fetch_prints_by_oracle_ids()` always deduplicates
the list before building the query (`list(dict.fromkeys(oracle_ids))`).

A failed batch (Scryfall query without a valid answer) marks none of its cards as checked — they are all
retried together on the next run, the same "never lose a card forever" principle already used for single
failures before the redesign.

### JSON Structure (`data/arena_rarity_data.json`)

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

`checked_cards[set_code]` lists **every** card already evaluated in that set, with or without an override
(not only those that got one). A new scan skips only the cards already listed here — runs after the first
cost only the cards that appeared since the last check, not the whole set.

**History**: until September 2026 the field was `processed_sets: ["SPG"]`, a "whole set done forever" flag —
right for a set that comes out once, wrong for one that grows over time. After the first successful scan,
every later run (manual ones included) became a permanent no-op, with no way to unblock it short of editing
the JSON by hand. A file in the old format no longer blocks anything: it is simply treated as "no card checked
yet" and rescanned once in full.

---

## 3. Arena Event Schedule Monitor (`utils/arena_event_schedule.py`)

### Problem

Wizards publishes a dedicated "**[Set] MTG Arena Event Schedule**" page (URL like
`magic.wizards.com/en/news/mtg-arena/the-hobbit-event-schedule`) once per expansion — not weekly like the "MTG
Arena Announcements" posts. It contains a "Full Event Calendar" section with the Quick Draft rotation and every
other recurring event, organized by category. There is no official API/RSS to know when a new page is
published or when an existing one is updated (Wizards edits it **in place** during the set's lifecycle, not
only at publication).

### Solution

`magic.wizards.com/en/sitemap.xml` is a standard XML sitemap with a `<lastmod>` for every page of the site. A
background task fetches the sitemap every 2 hours (a cheap request on a static file), filters the
`*-event-schedule` URLs under `/en/news/mtg-arena/` and picks the one with the **newest** `lastmod` — the
currently active set. Wizards doesn't remove past sets' pages from the sitemap: without this filter, at any
given time the sitemap always holds several (observed in production: 4 pages at once), and the first run on a
machine with an empty state would report them all as "new" at once, flooding notifications for events long
over. Only if the newest one is new or has a changed `lastmod` versus the saved state is the page itself
downloaded and parsed (fetch + HTML parsing, more expensive and fragile) — most checks do nothing beyond the
sitemap GET, because the real content only changes every 6-9 weeks.

The cadence (`_CHECK_INTERVAL_SECONDS` in `utils/sitemap_monitor.py`, shared by both monitors) is 2 hours.
Until 3.5.3 it was 24 hours: Wizards serves the sitemap with a `Cache-Control: max-age` of about 1 hour and
regenerates it *after* the article is published, so a page just out may not show up there for a while. On
2026-10-12 the daily check ran before the October Banned and Restricted appeared in the sitemap, and the next
run would have come almost 24 hours later. With 2 hours the maximum delay drops to about 3 hours, at the cost
of one extra ~660 KB GET every 2 hours per monitor.

| Function | Description |
|---|---|
| `check_event_schedule_updates(force=False)` | Finds the newest page in the sitemap; if new/changed (or always, with `force=True`) downloads+parses it; returns `[]` or `[{url, lastmod, categories}]` |
| `_pick_latest(entries)` | Local alias of `pick_latest_by_lastmod()` in `utils/sitemap_monitor.py` (shared with the Ban Announcement monitor) — picks the page with the highest `lastmod` |
| `parse_full_event_calendar(html)` | Extracts `{category: [entries]}` from the "Full Event Calendar" section; `None` if the section isn't found (structural site drift) |
| `periodic_event_schedule_check_loop(bot)` | Background task: calls `check_event_schedule_updates()` every 2 hours (first run right at startup), logs to Discord if the newest page is new/updated |
| `parse_event_entry(text)` | Extracts start and end month/day from a text entry ("Month Day[-Month] Day: Event name"); `None` if the format isn't recognized |
| `build_month_calendar(categories)` | Groups the entries by `(year, month)`, splitting multi-month ranges at month boundaries; the missing year is inferred from the current date |
| `send_event_schedule_log(logger, result, user, forced)` | Posts the result to Discord: one calendar image per month (Gantt per category colored by family + detailed list, generated by `EventCalendarImageGenerator`), attached to the same message instead of describing events in words — see `docs/adr/0001-event-calendar-image-layout.md` for the full design and the rejected alternatives |
| `extract_set_name_from_url(url)` | Derives a readable expansion name from the URL slug (e.g. `the-hobbit-event-schedule` → "The Hobbit"), used in the community embed title |
| `format_period_covered(month_calendar)` | Computes the overall period covered by every entry (min/max over `(year, month, day)`), in Italian, e.g. "11 Agosto - 29 Settembre 2026" |
| `get_latest_known_event_schedule()` | Reads (no network) the latest known page from the saved state — used by the `STARTUP_STATUS` log at bot startup |

`check_event_schedule_updates()` always prints an outcome to the console (`[EVENT SCHEDULE] ...`) — no
change, new/updated page, failed fetch, section not recognized — even when there is nothing to post to
Discord. Without this log, a run that finds no change (the most common outcome, since the real content only
changes every 6-9 weeks) is indistinguishable in the console from a task that never started — the source of
real confusion in production, where it looked like the check didn't run while it actually ran and correctly
found nothing new. Every line starts with a timestamp (`[2026-10-12 15:20:04] [EVENT SCHEDULE] ...`, the same
format as `discord.py`'s logs) via `log()` in `utils/console.py` (re-exported by `utils/sitemap_monitor.py`),
shared with the Ban Announcement monitor and the rest of the bot — without it, `pm2 logs` gave no way to tell
*when* a check ran relative to a page appearing in the sitemap.

### Parsing and Failure Handling

The "Full Event Calendar" section of these pages is genuinely structured HTML (not free prose like the weekly
Announcements posts): `<h2>/<h3>/<h4>Category</h2>` blocks followed by
`<ul><li>date range: description</li></ul>`, bounded between the "Full Event Calendar" heading and the next
`</article>` — this boundary (`</article>`), not the heading attributes, is what keeps out the side navigation
cards (which live outside the `<article>`). The "Full Event Calendar" heading itself can carry attributes
(`<h2 id="FRACalendar" style="...">`, seen on `reality-fracture-event-schedule`, September 2026) —
`_CALENDAR_HEADING_RE` tolerates them; only the category headings (`<h3>Premier Draft</h3>` etc.) stay bare on
every page observed so far.

If the expected structure isn't found, `parse_full_event_calendar()` returns `None` instead of a partial or
wrong summary — the caller logs a `WARN` ("a manual check is recommended") instead of posting potentially
unreliable data as if it were authoritative. A failed network fetch (page unreachable) doesn't update the
saved state: it is retried on the next run instead of being marked as "already seen".

### State (`data/arena_event_schedule_state.json`, not tracked in git)

```json
{
  "latest_url": "https://magic.wizards.com/en/news/mtg-arena/the-hobbit-event-schedule",
  "latest_lastmod": "2026-09-02T16:05:08.364Z"
}
```

Tracks only the latest (newest) page actually processed, not the whole history — pure operational
bookkeeping; unlike `arena_rarity_data.json` it holds no curated/editorial data, so it isn't tracked in git
(see `.gitignore`). Written atomically (`save_json_state()`: `.tmp` + `os.replace`).

Admin command (`ADMIN_ROLE` role, default `Staff`) to force an immediate check (ignores the `lastmod`
comparison, re-checks the newest page in the sitemap anyway): `/forced_event_schedule_check`. When the
calendar is generated successfully, the images are posted both to the log channel and to
`COMUNICATION_CHANNEL_ID` (public channel, with a dedicated Italian embed without staff jargon — title with the
expansion name "📅 Calendario Eventi Arena — <set>", body with the period covered and the source link); the two
WARN cases (unparseable page or no dates) stay in the log channel only. There used to be a separate
`/preview_calendario_eventi` command for a manual preview outside the log channel — removed once
`/forced_event_schedule_check` started posting to the community channel too, making it redundant.

---

## 3b. Banned and Restricted Announcement Monitor (`utils/ban_announcement.py`)

### Problem

Wizards publishes a "**Banned and Restricted Announcement**" on a fixed cadence (roughly every 6 weeks, always
on a Monday — URL like `magic.wizards.com/en/news/announcements/banned-and-restricted-august-10-2026`) covering
every official constructed format (Standard, Pioneer, Modern, Legacy, Vintage, Pauper, Alchemy, Historic,
Timeless, Brawl, Competitive Brawl). None of them is this community's homebrew **Artisan**: the bot's banlist
(`banned_cards`, see `docs/banlist-system.md`) is a hand-curated list, independent of Wizards' official
decisions. This monitor only **notifies** that a new announcement is out — it never writes to the banlist.

### Solution

Same scheme as the Event Schedule monitor: these pages are also listed in `magic.wizards.com/en/sitemap.xml`
with `<lastmod>`, and Wizards doesn't remove past announcements from the sitemap, so only the one with the
newest `lastmod` is considered (`_pick_latest()`). The sitemap check runs every 2 hours (cheap, same shared
cadence); fetching+parsing the page itself only happens if the newest announcement's `lastmod` changed. As for
the Event Schedule, every run prints a timestamped outcome to the console
(`[2026-10-12 15:20:04] [BAN ANNOUNCEMENT] ...`).

Unlike the Event Schedule, the page has no date-list section, just free prose per format. Every
`<h2>Format</h2>` section is, however, followed by a reliable, structured summary:
`<p style="padding-left: 30px;">Card X is banned.<br/>Card Y is unbanned.</p>` (or literally `"No changes"`
when the format doesn't change) — verified live on the August/June/March 2026 announcements.
`parse_ban_announcement()` extracts only this summary, never the surrounding analysis prose or the sample
decklists (too unstructured for reliable extraction, and out of scope anyway for a bot that only notifies).

| Function | Description |
|---|---|
| `check_ban_announcement_updates(force=False)` | Finds the newest announcement in the sitemap; if new/changed (or always, with `force=True`) downloads+parses it; returns `[]` or `[{url, lastmod, changes, already_notified}]` — `already_notified` is `True` if that same URL's changes were already posted to the community channel |
| `_pick_latest(entries)` | Same alias of `pick_latest_by_lastmod()` (`utils/sitemap_monitor.py`) as the Event Schedule monitor |
| `parse_ban_announcement(html)` | Extracts `{format: [change lines]}` from each section's summary; formats with `"No changes"` are left out; `{}` if the announcement is parsed but no format changed (a valid outcome), `None` if not even one structured summary is found (site drift) |
| `periodic_ban_announcement_check_loop(bot)` | Background task: calls `check_ban_announcement_updates()` every 2 hours (first run right at startup), logs to Discord if the newest announcement is new |
| `send_ban_announcement_log(logger, result, user, forced)` | Posts the result to Discord: one embed field per changed format (`Logger.send_log()`'s `fields`). If there are real changes and the announcement isn't `already_notified`, it also goes to `COMUNICATION_CHANNEL_ID` (`extra_channel_id`) with a dedicated Italian embed (title with the announcement's date/time, body with just the link — no staff jargon) besides the log channel; WARN/no-change cases stay in the log channel only |
| `format_lastmod(lastmod)` | Formats the sitemap's ISO-8601 timestamp in Italian (e.g. "21 Agosto 2026, 18:02 UTC"), used in the community embed title — the only date+time available, the page shows just the day |
| `get_latest_known_ban_announcement()` | Reads (no network) the latest known announcement from the saved state — used by the `STARTUP_STATUS` log at bot startup |

### State (`data/ban_announcement_state.json`, not tracked in git)

```json
{
  "latest_url": "https://magic.wizards.com/en/news/announcements/banned-and-restricted-august-10-2026",
  "latest_lastmod": "2026-08-21T18:02:33.573Z",
  "notified_url": "https://magic.wizards.com/en/news/announcements/banned-and-restricted-august-10-2026"
}
```

The same operational bookkeeping (not curated data) as the Event Schedule state — not tracked in git.

`notified_url` (since 3.5.3) is the latest announcement whose changes were posted to the community channel. It
is needed because, unlike the Event Schedule, a new `lastmod` on the *same* URL is not new content for the
community: Wizards touches these announcements days later (the August 10 one has `lastmod` August 21), and a
`/forced_ban_announcement_check` on the already known announcement would repost it as "Nuovo" (observed on
2026-10-12, when the forced check ran before the October announcement appeared in the sitemap and reposted the
August one). In these cases the result is still re-read and posted to the log channel, but not to the
community channel. `notified_url` is updated only when there are real changes: an all-"No changes"
announcement later edited with real changes is still announced. A state saved before 3.5.3 has no such field:
`latest_url` counts as notified, so the upgrade doesn't repost the last announcement already processed.

Admin command (`ADMIN_ROLE` role, default `Staff`) to force an immediate check (ignores the `lastmod`
comparison): `/forced_ban_announcement_check`. If the newest announcement was already notified to the
community, the re-check posts to the log channel only.

### Startup Status Log (`STARTUP_STATUS`)

Right after `SYSTEM_STARTUP`, `main.py` posts a second `STARTUP_STATUS` log (log channel only, no
`extra_channel_id`) reporting the latest Event Schedule page and the latest Banned and Restricted
Announcement already known to the bot — read by `get_latest_known_event_schedule()`/
`get_latest_known_ban_announcement()`, plain reads of the state saved on disk, **with no network request**.
It is an at-a-glance check on every restart, distinct from the real periodic check (which runs shortly after,
when the four `periodic_*_loop()` tasks start, and actually queries the sitemap).

---

## 4. Scryfall API — Strategy

### Endpoints

| Endpoint | Use | Limit |
|---|---|---|
| `POST /cards/collection` | Batch card fetch (max 75 per chunk) | 100ms between requests |
| `GET prints_search_uri + game:arena` | Checks a single card's Arena printings | — |

### Rate Limiting

```python
_SCRYFALL_SEMAPHORE = asyncio.Semaphore(1)  # 1 request at a time
_MIN_REQUEST_INTERVAL = 0.11  # 110ms between requests (above the 100ms limit)
```

### Retry Logic

- Exponential backoff on status 429 (reading the `Retry-After` header), on 5xx and on network errors/timeouts
- Timeout: 120s overall for one validation's session (`aiohttp.ClientTimeout(total=120)`)
- At most 5 attempts per request, then `ScryfallUnavailable` — never cached as an "illegal card"; a 404 (no
  Arena printings) is instead a valid outcome. See `docs/deck-validation.md` "Scryfall Unreachable"

### Alchemy Filter

Alchemy printings are not allowed in Artisan: when evaluating the `prints_search_uri` + `game:arena` results,
`_is_arena_artisan_legal()` skips printings with `set_type=alchemy` whose name starts with `A-`.

---

## 5. Banlist Cache

The banlist (`BannedCard` in SQLite) is cached in memory in the module variable
`_banlist_cache: set[str] | None` in `cogs/deck_validation/service.py`, shared by every `ArtisanService`
instance.

| Aspect | Detail |
|---|---|
| Loading | First validation after startup (or after an invalidation): `await BanlistRepository.get_all_for_format()`, then expanded with `_expand_double_faced()` (adds the front half alone of double-faced cards — see `docs/banlist-system.md` "Known Issues") |
| Validity | Until the next explicit invalidation |
| Invalidation | `ArtisanService.reload_banlist()` (wrapper over `invalidate_banlist_cache()`), called by `/banlist_aggiungi` and `/banlist_rimuovi` right after writing to the DB — the effect is visible from every instance, not only the one it is called on |

---

## Cache Summary

| Cache | Location | Persistence | Invalidation |
|---|---|---|---|
| Scryfall cards | SQLite table `cached_cards` | Every 60s + at shutdown, incremental (changed entries only) | `artisan_legal` with a 30-day TTL; `/invalidate_card_cache` for a single card |
| Rarity overrides | `arena_rarity_data.json` | On update | Explicit (`invalidate_override_cache()`) |
| Arena Event Schedule | `arena_event_schedule_state.json` | Check every 2 hours (parsing only on a changed `lastmod`) | `/forced_event_schedule_check` (ignores `lastmod`) |
| Banned and Restricted | `ban_announcement_state.json` | Check every 2 hours (parsing only on a changed `lastmod`) | `/forced_ban_announcement_check` (ignores `lastmod`) |
| Banlist | `_banlist_cache` (module) | Shared across instances | Explicit (`reload_banlist()` after add/remove) |
