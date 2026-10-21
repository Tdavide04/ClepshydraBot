"""
event_schedule.py

Detects publication or updates of Wizards' "[Set] MTG Arena Event Schedule"
pages (one per expansion, not weekly like the "MTG Arena Announcements"
posts) and extracts their "Full Event Calendar" section, to notify the
community without anyone checking the site by hand.

Approach:
- magic.wizards.com/en/sitemap.xml is a standard XML sitemap with a <lastmod>
  for every page on the site. Filtering the "*-event-schedule" URLs under
  /en/news/mtg-arena/ yields the list of existing schedule pages without
  guessing the next set's name in advance.
- Wizards updates these pages IN PLACE during the set's lifecycle (e.g. to
  add the following weeks of Quick Draft rotation), rather than publishing
  them once: that is why lastmod is compared, not just the URL's presence.
- Wizards does NOT remove past sets' pages from the sitemap: at any given
  time it lists several (one per recent set). Only the CURRENTLY active
  set's page matters, not the whole history - so only the page with the
  newest lastmod is considered, not all of them. Without this filter, the
  first run on a new machine (empty state) would report as "new" pages of
  sets that ended months ago, flooding notifications for events no longer
  relevant.
- The sitemap check is cheap (a GET on a static file) and runs every 2
  hours; fetching+parsing the page itself (more expensive and fragile,
  being HTML rather than a data format) only happens for URLs whose lastmod
  is new or changed versus the saved state.
- The "Full Event Calendar" section of these pages is genuinely structured
  HTML (not free prose like the weekly Announcements posts):
  <h2>/<h3>/<h4>Category</h2> blocks followed by <ul><li>date range:
  description</li></ul>. If this structure isn't found (site drift), the
  page is reported as unparseable instead of publishing an incomplete or
  wrong summary.
"""

import asyncio
import calendar
import html as html_module
import re
import xml.etree.ElementTree as ET
from datetime import date

import aiohttp
import discord

from core.console import log
from core.json_state import load_json_state, save_json_state
from features.monitors.sitemap import (
    _CHECK_INTERVAL_SECONDS,
    _SITEMAP_NS,
    fetch_page_html,
    fetch_sitemap_xml,
    pick_latest_by_lastmod,
)

STATE_PATH = "data/arena_event_schedule_state.json"

# Sub-path hosting both the weekly "announcements-*" posts and the dedicated
# "*-event-schedule" pages this module watches.
_NEWS_URL_PREFIX = "https://magic.wizards.com/en/news/mtg-arena/"

_EVENT_SCHEDULE_URL_RE = re.compile(re.escape(_NEWS_URL_PREFIX) + r"[a-z0-9-]+-event-schedule$")

_HEADING_LIST_RE = re.compile(
    r"<h[234]>\s*([^<]+?)\s*</h[234]>\s*<ul>(.*?)</ul>",
    re.DOTALL,
)
_LI_RE = re.compile(r"<li>(.*?)</li>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
# [^>]* tolerates attributes on the heading tag (e.g. reality-fracture-event-schedule
# has <h2 id="FRACalendar" style="scroll-margin-top: 70px;">Full Event
# Calendar</h2> instead of the bare <h2> seen on earlier pages - the actual
# cause of an ARENA_EVENT_SCHEDULE_UNPARSEABLE WARN in production on
# 2026-09-21). The category headings below (_HEADING_LIST_RE) stay bare on
# that page, so they don't need the same tolerance.
_CALENDAR_HEADING_RE = re.compile(r"<h[234][^>]*>\s*Full Event Calendar\s*</h[234]>")
_ARTICLE_END_RE = re.compile(r"</article>")

# Every "Full Event Calendar" entry has the format observed live
# "Month Day[-Month] Day: Event name" (e.g. "August 11-September 29: ...",
# "August 11-19: ..."), with no explicit year - the end month is optional
# when the range stays within the same month. The dash can be an en dash
# (the one the site actually uses) or a plain "-".
_ENTRY_DATE_RE = re.compile(
    r"^(?P<m1>[A-Za-z]+)\s+(?P<d1>\d{1,2})\s*[–-]\s*"
    r"(?:(?P<m2>[A-Za-z]+)\s+)?(?P<d2>\d{1,2})\s*:\s*(?P<name>.+)$"
)

_MONTH_NUMBERS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

MONTHS_IT = {
    1: "Gennaio",
    2: "Febbraio",
    3: "Marzo",
    4: "Aprile",
    5: "Maggio",
    6: "Giugno",
    7: "Luglio",
    8: "Agosto",
    9: "Settembre",
    10: "Ottobre",
    11: "Novembre",
    12: "Dicembre",
}

_state_cache: dict | None = None


# ==========================================
# LOAD / SAVE STATE
# ==========================================


def _load_state() -> dict:
    global _state_cache

    if _state_cache is not None:
        return _state_cache

    _state_cache = load_json_state(STATE_PATH, {"latest_url": None, "latest_lastmod": None})
    return _state_cache


def _save_state(data: dict) -> None:
    global _state_cache

    save_json_state(STATE_PATH, data)
    _state_cache = data


def invalidate_state_cache() -> None:
    global _state_cache
    _state_cache = None


def get_latest_known_event_schedule() -> dict:
    """Returns the latest Event Schedule page known from the state saved on
    disk - {"url": str | None, "lastmod": str | None} - with no network
    request. Used by the startup status log (main.py), distinct from the real
    periodic check: here the point is only to show what the bot already
    knows, not to check for anything new."""

    state = _load_state()
    return {"url": state.get("latest_url"), "lastmod": state.get("latest_lastmod")}


# ==========================================
# SITEMAP
# ==========================================


def _parse_sitemap_xml(body: str) -> dict[str, str]:
    """Extracts {url: lastmod} for the '*-event-schedule' pages under
    /en/news/mtg-arena/ only. Kept separate from the HTTP fetch so it can be
    tested without mocking aiohttp."""

    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        log(f"[SITEMAP PARSE ERROR] {e}")
        return {}

    found: dict[str, str] = {}
    for url_el in root.findall("sm:url", _SITEMAP_NS):
        loc_el = url_el.find("sm:loc", _SITEMAP_NS)
        lastmod_el = url_el.find("sm:lastmod", _SITEMAP_NS)

        if loc_el is None or loc_el.text is None:
            continue

        loc = loc_el.text.strip()
        if not _EVENT_SCHEDULE_URL_RE.match(loc):
            continue

        found[loc] = lastmod_el.text.strip() if lastmod_el is not None and lastmod_el.text else ""

    return found


async def _fetch_sitemap_event_schedule_urls(
    session: aiohttp.ClientSession,
) -> dict[str, str]:
    """Fetches the sitemap and returns {url: lastmod} for the
    '*-event-schedule' pages under /en/news/mtg-arena/ only."""

    body = await fetch_sitemap_xml(session)
    if body is None:
        return {}

    return _parse_sitemap_xml(body)


# ==========================================
# PARSING THE "FULL EVENT CALENDAR" PAGE
# ==========================================


def _strip_tags(text: str) -> str:
    return html_module.unescape(_TAG_RE.sub("", text)).strip()


def parse_full_event_calendar(page_html: str) -> dict[str, list[str]] | None:
    """Extracts {category: [entries]} from the 'Full Event Calendar' section
    of an Event Schedule page. Returns None if the section isn't found
    (structural site drift) - the caller must treat it as 'unparseable', not
    as 'no events'."""

    calendar_match = _CALENDAR_HEADING_RE.search(page_html)
    if not calendar_match:
        return None

    section = page_html[calendar_match.end() :]
    end_match = _ARTICLE_END_RE.search(section)
    if end_match:
        section = section[: end_match.start()]

    categories: dict[str, list[str]] = {}
    for heading, list_block in _HEADING_LIST_RE.findall(section):
        category = _strip_tags(heading)
        entries = [_strip_tags(li) for li in _LI_RE.findall(list_block)]
        entries = [e for e in entries if e]
        if category and entries:
            categories[category] = entries

    return categories or None


# ==========================================
# ENTRY DATE PARSING + GROUPING BY MONTH
# ==========================================


def parse_event_entry(text: str) -> dict | None:
    """Extracts start and end month/day from a 'Full Event Calendar' text
    entry (e.g. 'August 11-September 29: Event name' or 'August 11-19: Event
    name'). Returns None if the text doesn't follow the expected format - the
    caller must leave the entry out of the calendar image instead of making
    up a date, but can still show it untouched in text embeds (which don't
    depend on this parsing)."""

    match = _ENTRY_DATE_RE.match(text.strip())
    if not match:
        return None

    m1 = _MONTH_NUMBERS.get(match.group("m1").lower())
    m2_raw = match.group("m2")
    m2 = _MONTH_NUMBERS.get(m2_raw.lower()) if m2_raw else m1

    if m1 is None or m2 is None:
        return None

    try:
        d1 = int(match.group("d1"))
        d2 = int(match.group("d2"))
    except ValueError:
        return None

    return {
        "start_month": m1,
        "start_day": d1,
        "end_month": m2,
        "end_day": d2,
        "name": match.group("name").strip(),
    }


def _infer_start_year(start_month: int, reference: date) -> int:
    """Assumes the current year at check time; if the start month is far
    "behind" the current month (e.g. January when the check runs in
    December), it is taken as next year rather than a past one - covers the
    year boundary for a range published at year end. The threshold (6
    months) avoids false positives on "Flashback" entries that correctly
    refer to a recent month of the same year."""

    diff = start_month - reference.month
    if diff <= -6:
        return reference.year + 1
    return reference.year


def build_month_calendar(
    categories: dict[str, list[str]],
    reference_date: date | None = None,
) -> dict[tuple[int, int], dict[str, list[tuple[int, int, str]]]]:
    """Turns {category: [text entries]} into
    {(year, month): {category: [(start_day, end_day, name), ...]}},
    splitting every range spanning several months into one segment per
    month it touches (days are clipped to the month's bounds). Unparseable
    entries (unexpected date format) are silently left out - they stay
    visible only in text embeds, which don't go through here."""

    if reference_date is None:
        reference_date = date.today()

    result: dict[tuple[int, int], dict[str, list[tuple[int, int, str]]]] = {}

    for category, entries in categories.items():
        for entry_text in entries:
            parsed = parse_event_entry(entry_text)
            if parsed is None:
                continue

            start_year = _infer_start_year(parsed["start_month"], reference_date)
            end_year = start_year
            if parsed["end_month"] < parsed["start_month"]:
                end_year = start_year + 1

            cur_year, cur_month = start_year, parsed["start_month"]
            while (cur_year, cur_month) <= (end_year, parsed["end_month"]):
                if (cur_year, cur_month) == (start_year, parsed["start_month"]):
                    seg_start = parsed["start_day"]
                else:
                    seg_start = 1

                if (cur_year, cur_month) == (end_year, parsed["end_month"]):
                    seg_end = parsed["end_day"]
                else:
                    seg_end = calendar.monthrange(cur_year, cur_month)[1]

                month_key = (cur_year, cur_month)
                result.setdefault(month_key, {}).setdefault(category, []).append(
                    (seg_start, seg_end, parsed["name"])
                )

                if cur_month == 12:
                    cur_year, cur_month = cur_year + 1, 1
                else:
                    cur_month += 1

    return result


def extract_set_name_from_url(url: str) -> str:
    """Derives a readable expansion name from the Event Schedule page slug
    (e.g. '.../the-hobbit-event-schedule' -> 'The Hobbit'). The page has no
    dedicated set-name field that can be extracted reliably (the name only
    shows up inside assorted prose/HTML), but the slug is always present and
    stable, so it is the safest source for a readable community title."""

    slug = url.rstrip("/").rsplit("/", 1)[-1]
    if slug.endswith("-event-schedule"):
        slug = slug[: -len("-event-schedule")]

    return " ".join(word.capitalize() for word in slug.split("-") if word)


def format_period_covered(
    month_calendar: dict[tuple[int, int], dict[str, list[tuple[int, int, str]]]],
) -> str | None:
    """Formats, in Italian (it is shown to the community), the overall
    period covered by every entry of a calendar already built by
    build_month_calendar() (e.g. '11 Agosto - 29 Settembre 2026'), or None
    if the calendar is empty. The chronological comparison uses (year,
    month, day) tuples: since the (year, month) keys are already in
    chronological order and days are clipped to month bounds for the middle
    segments, min/max over these tuples matches the real start/end of the
    original range, without rebuilding the pre-split ranges."""

    starts: list[date] = []
    ends: list[date] = []

    for (year, month), category_entries in month_calendar.items():
        for entries in category_entries.values():
            for day_start, day_end, _ in entries:
                starts.append(date(year, month, day_start))
                ends.append(date(year, month, day_end))

    if not starts:
        return None

    period_start, period_end = min(starts), max(ends)

    if period_start.year == period_end.year:
        return (
            f"{period_start.day} {MONTHS_IT[period_start.month]} - "
            f"{period_end.day} {MONTHS_IT[period_end.month]} {period_end.year}"
        )

    return (
        f"{period_start.day} {MONTHS_IT[period_start.month]} {period_start.year} - "
        f"{period_end.day} {MONTHS_IT[period_end.month]} {period_end.year}"
    )


# In practice this selects the currently active set - see
# pick_latest_by_lastmod() in features/monitors/sitemap.py for the rationale.
_pick_latest = pick_latest_by_lastmod


async def _fetch_page_html(session: aiohttp.ClientSession, url: str) -> str | None:
    return await fetch_page_html(session, url, log_prefix="EVENT SCHEDULE")


# ==========================================
# CHECK (public API)
# ==========================================


async def check_event_schedule_updates(force: bool = False) -> list[dict]:
    """Finds the NEWEST Event Schedule page (by lastmod) in the sitemap and,
    if it is new or changed versus the last known one (or anyway, if
    force=True), fetches it and tries to parse the 'Full Event Calendar'
    section. Past sets' pages still listed in the sitemap are ignored (see
    _pick_latest).

    Returns a list with zero or one {url, lastmod, categories} item
    (categories None if parsing failed - the caller must report it as such,
    not silently ignore it) - the list shape stays for compatibility with
    callers that iterate over the result. Updates and saves the state only if
    the page was actually processed in this call.
    """

    headers = {"User-Agent": "ClepshydraBot/1.0 (Discord Tournament Bot)"}
    timeout = aiohttp.ClientTimeout(total=60)

    state = _load_state()

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        current = await _fetch_sitemap_event_schedule_urls(session)

        latest = _pick_latest(current)
        if latest is None:
            log("[EVENT SCHEDULE] no Event Schedule page found in the sitemap")
            return []

        url, lastmod = latest

        already_seen = state.get("latest_url") == url and state.get("latest_lastmod") == lastmod
        if already_seen and not force:
            log(f"[EVENT SCHEDULE] no change (latest: {url})")
            return []

        log(f"[EVENT SCHEDULE] new/updated page: {url}")

        page_html = await _fetch_page_html(session, url)

        if page_html is None:
            # Fetch failed: leave the state untouched and retry on the next
            # run instead of marking the page as seen.
            log(f"[EVENT SCHEDULE] fetch failed for {url}, retrying on the next run")
            return []

        categories = parse_full_event_calendar(page_html)

    _save_state({"latest_url": url, "latest_lastmod": lastmod})

    if categories is None:
        log(f"[EVENT SCHEDULE] {url}: 'Full Event Calendar' section not recognized")
    else:
        log(f"[EVENT SCHEDULE] {url}: {len(categories)} categories parsed")

    return [{"url": url, "lastmod": lastmod, "categories": categories}]


async def periodic_event_schedule_check_loop(
    bot=None,
    interval_seconds: int = _CHECK_INTERVAL_SECONDS,
) -> None:
    """Background task: checks the sitemap every 2 hours and notifies
    Discord of every new or updated Event Schedule page. The first run starts
    right at startup, like periodic_spg_refresh_loop."""

    while True:
        try:
            results = await check_event_schedule_updates()

            if results and bot is not None:
                logger = bot.get_cog("Logger")
                if logger:
                    for result in results:
                        await send_event_schedule_log(logger, result, user=None, forced=False)

        except Exception as e:
            log(f"[EVENT SCHEDULE AUTO-CHECK] error: {e}")

        await asyncio.sleep(interval_seconds)


async def send_event_schedule_log(logger, result: dict, user, forced: bool) -> None:
    """Posts to Discord (via the Logger cog) the outcome of checking a single
    Event Schedule page. Public because both the automatic loop and the
    manual admin command use it (same log format for both paths).

    Generates and attaches one calendar image per month
    (EventCalendarImageGenerator) instead of describing events in words in
    embed fields - replaces the previous design (one field per category,
    split across several messages), hard to read with the 13-15 real
    categories. EventCalendarImageGenerator is imported inside the function
    (not at module top) to avoid a circular import: that module imports
    MONTHS_IT from here.

    When the calendar is generated successfully, the images are also posted
    to COMUNICATION_CHANNEL_ID (via Logger.send_log()'s `extra_channel_id`,
    same scheme as send_ban_announcement_log() in features/monitors/ban_announcement.py)
    - a real update concerns the whole community, not just staff. That
    channel is public (@everyone gets pinged): `community_title` /
    `community_info` build a dedicated Italian embed without the staff
    jargon ("Forced manual check", the user who invoked the command) that
    stays in the log channel's `info` - only the images are shared between
    the two posts. The two WARN cases (unparseable page or no dates) stay in
    the log channel only: they are operational noise for whoever maintains
    the bot, not content for the community. COMUNICATION_CHANNEL_ID is
    imported lazily (as in ban_announcement.py, see core/permissions.py for
    the same pattern) to stay importable in tests without a full .env."""

    url = result["url"]
    categories = result["categories"]
    prefix = "Forced manual check" if forced else "Automatic check"

    if categories is None:
        await logger.send_log(
            level="WARN",
            event="ARENA_EVENT_SCHEDULE_UNPARSEABLE",
            user=user,
            info=(
                f"{prefix}: found an update on {url} but the "
                f"'Full Event Calendar' section was not recognized (the site "
                f"structure may have changed). A manual check is recommended."
            ),
        )
        return

    month_calendar = build_month_calendar(categories)

    if not month_calendar:
        await logger.send_log(
            level="WARN",
            event="ARENA_EVENT_SCHEDULE_NO_DATES",
            user=user,
            info=(
                f"{prefix}: {url} parsed but no entry had a recognizable "
                f"date format - calendar not generated, a manual check is "
                f"recommended."
            ),
        )
        return

    from features.monitors.calendar_image import EventCalendarImageGenerator

    files = [
        discord.File(
            EventCalendarImageGenerator.create_month_calendar(year, month, category_entries),
            filename=f"calendario_{year}_{month:02d}.png",
        )
        for (year, month), category_entries in sorted(month_calendar.items())
    ]

    from config.config import COMUNICATION_CHANNEL_ID

    set_name = extract_set_name_from_url(url)
    period = format_period_covered(month_calendar)
    period_line = f"**Periodo:** {period}\n" if period else ""

    await logger.send_log(
        level="INFO",
        event="ARENA_EVENT_SCHEDULE_UPDATED",
        user=user,
        info=f"{prefix}: {url}",
        files=files,
        extra_channel_id=COMUNICATION_CHANNEL_ID,
        community_title=f"📅 Calendario Eventi Arena — {set_name}",
        community_info=f"{period_line}[Fonte]({url})",
    )
