"""
ban_announcement.py

Detects the publication of a new Wizards "Banned and Restricted Announcement"
(magic.wizards.com/en/news/announcements/banned-and-restricted-*), published
on a fixed cadence (roughly every 6 weeks, always on a Monday), to notify the
community - without touching the bot's Artisan banlist, which stays a
hand-curated list (see docs/banlist-system.md): none of the official Wizards
formats listed in these announcements (Standard, Pioneer, Modern, Legacy,
Vintage, Pauper, Alchemy, Historic, Timeless, Brawl, Competitive Brawl) is
this community's homebrew Artisan, so there is no correct way to apply these
changes to the bot automatically.

Approach (same scheme as arena_event_schedule.py):
- The magic.wizards.com/en/sitemap.xml sitemap lists these announcements too,
  with <lastmod>. As with the Event Schedule pages, Wizards doesn't remove
  past announcements from the sitemap, so several always coexist - only the
  one with the newest lastmod matters (_pick_latest), otherwise the first run
  on a new machine would report the whole history as "new" at once.
- The sitemap check runs every 2 hours (a cheap GET on a static file);
  fetching+parsing the page itself (more fragile, HTML rather than
  structured data) only happens if the newest announcement's lastmod changed
  versus the saved state.
- Unlike the Event Schedule, there is no date-list section here, just free
  prose per format. Observed live, though, that every section has a
  reliable, structured summary right below the format heading:
  <h2>Format</h2> ... <p style="padding-left: 30px;">Card X is banned.
  <br/>Card Y is unbanned.</p> (or literally "No changes" when nothing
  changes in that format). Only this summary is extracted - the rest of the
  article (metagame analysis, sample decklists) is left alone: parsing it
  would be too fragile to be reliable, and it is out of scope anyway for a
  bot that only notifies rather than summarizing the article.
- If not even one format heading with the expected summary is found, the
  page is reported as unparseable (site drift) instead of publishing an
  empty or wrong summary - same philosophy as parse_full_event_calendar() in
  arena_event_schedule.py.
"""

import asyncio
import html as html_module
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import aiohttp

from utils.arena_event_schedule import MONTHS_IT
from utils.sitemap_monitor import (
    _CHECK_INTERVAL_SECONDS,
    _SITEMAP_NS,
    fetch_page_html,
    fetch_sitemap_xml,
    load_json_state,
    log,
    pick_latest_by_lastmod,
    save_json_state,
)

STATE_PATH = "data/ban_announcement_state.json"

_ANNOUNCEMENTS_URL_PREFIX = "https://magic.wizards.com/en/news/announcements/banned-and-restricted-"

_BAN_ANNOUNCEMENT_URL_RE = re.compile(re.escape(_ANNOUNCEMENTS_URL_PREFIX) + r"[a-z0-9-]+$")

_H2_RE = re.compile(r"<h2[^>]*>\s*([^<]+?)\s*</h2>")

# Each format's summary is the only <p> with this inline style seen on the
# real pages - not dedicated semantic markup, but stable across every
# announcement checked (August/June/March 2026).
_SUMMARY_P_RE = re.compile(
    r'<p[^>]*style="[^"]*padding-left:\s*30px[^"]*"[^>]*>(.*?)</p>',
    re.DOTALL,
)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

_state_cache: dict | None = None


# ==========================================
# LOAD / SAVE STATE
# ==========================================


def _load_state() -> dict:
    global _state_cache

    if _state_cache is not None:
        return _state_cache

    _state_cache = load_json_state(
        STATE_PATH, {"latest_url": None, "latest_lastmod": None, "notified_url": None}
    )
    return _state_cache


def _save_state(data: dict) -> None:
    global _state_cache

    save_json_state(STATE_PATH, data)
    _state_cache = data


def invalidate_state_cache() -> None:
    global _state_cache
    _state_cache = None


def get_latest_known_ban_announcement() -> dict:
    """Returns the latest Banned and Restricted Announcement known from the
    state saved on disk - {"url": str | None, "lastmod": str | None} - with
    no network request. Same role as get_latest_known_event_schedule() in
    arena_event_schedule.py: used by the startup status log."""

    state = _load_state()
    return {"url": state.get("latest_url"), "lastmod": state.get("latest_lastmod")}


def _notified_url(state: dict) -> str | None:
    """URL of the latest announcement whose changes were posted to the
    community channel. A state saved before 3.5.3 has no such field: in that
    case the last processed announcement (latest_url) counts as notified, so
    the upgrade doesn't repost it, while a new one still gets notified."""

    if "notified_url" in state:
        return state["notified_url"]
    return state.get("latest_url")


# ==========================================
# SITEMAP
# ==========================================


def _parse_sitemap_xml(body: str) -> dict[str, str]:
    """Extracts {url: lastmod} for the 'banned-and-restricted-*' pages
    under /en/news/announcements/ only. Kept separate from the HTTP fetch so
    it can be tested without mocking aiohttp."""

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
        if not _BAN_ANNOUNCEMENT_URL_RE.match(loc):
            continue

        found[loc] = lastmod_el.text.strip() if lastmod_el is not None and lastmod_el.text else ""

    return found


async def _fetch_sitemap_ban_urls(session: aiohttp.ClientSession) -> dict[str, str]:
    """Fetches the sitemap and returns {url: lastmod} for the
    'banned-and-restricted-*' pages under /en/news/announcements/ only."""

    body = await fetch_sitemap_xml(session)
    if body is None:
        return {}

    return _parse_sitemap_xml(body)


# ==========================================
# PARSING THE ANNOUNCEMENT PAGE
# ==========================================


def _strip_tags(text: str) -> str:
    return html_module.unescape(_TAG_RE.sub("", text)).strip()


def parse_ban_announcement(page_html: str) -> dict[str, list[str]] | None:
    """Extracts {format: [change lines]} from the summary of every
    <h2>Format</h2> section of a Banned and Restricted announcement. Formats
    with no changes ("No changes") are left out of the result - an empty
    dict is therefore a valid outcome (no format touched this time), not an
    error. Returns None only if not even one structured summary is found
    (site drift) - the caller must treat it as "unparseable", not as "no
    changes"."""

    headings = list(_H2_RE.finditer(page_html))
    if not headings:
        return None

    changes: dict[str, list[str]] = {}
    found_any_summary = False

    for i, heading in enumerate(headings):
        format_name = html_module.unescape(heading.group(1)).strip()
        start = heading.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(page_html)
        chunk = page_html[start:end]

        summary_match = _SUMMARY_P_RE.search(chunk)
        if not summary_match:
            continue
        found_any_summary = True

        lines = [_strip_tags(part) for part in _BR_RE.split(summary_match.group(1))]
        lines = [line for line in lines if line]

        if not lines or (len(lines) == 1 and lines[0].lower() == "no changes"):
            continue

        changes[format_name] = lines

    if not found_any_summary:
        return None

    return changes


def format_lastmod(lastmod: str) -> str:
    """Formats the sitemap's ISO-8601 timestamp in Italian, since it goes
    into the community embed (e.g. '2026-08-21T18:02:33.573Z' -> '21 Agosto
    2026, 18:02 UTC'). It is the only date+time available for the
    announcement: the page shows a <time> with the day only (e.g. 'Aug 10,
    2026'), no time of day, and it reflects Wizards' last edit to the page
    anyway, not necessarily the moment of first publication. Returns the
    original string unchanged if the format isn't the expected one, instead
    of failing the notification over a cosmetic detail."""

    try:
        dt = datetime.fromisoformat(lastmod.replace("Z", "+00:00"))
    except ValueError:
        return lastmod

    return f"{dt.day} {MONTHS_IT[dt.month]} {dt.year}, {dt.strftime('%H:%M')} UTC"


# Same newest-lastmod selection as arena_event_schedule.py - see
# pick_latest_by_lastmod() in utils/sitemap_monitor.py.
_pick_latest = pick_latest_by_lastmod


async def _fetch_page_html(session: aiohttp.ClientSession, url: str) -> str | None:
    return await fetch_page_html(session, url, log_prefix="BAN ANNOUNCEMENT")


# ==========================================
# CHECK (public API)
# ==========================================


async def check_ban_announcement_updates(force: bool = False) -> list[dict]:
    """Finds the NEWEST Banned and Restricted announcement (by lastmod) in
    the sitemap and, if it is new versus the last known one (or anyway if
    force=True), fetches it and tries to parse its per-format summary. Past
    announcements still listed in the sitemap are ignored (see _pick_latest).

    Returns a list with zero or one {url, lastmod, changes, already_notified}
    item (changes None if parsing failed, {} if parsed but with no format
    changed) - the list shape stays for consistency with
    check_event_schedule_updates(). Updates and saves the state only if the
    page was actually processed in this call.

    already_notified is True if this same URL's changes were already posted
    to the community channel: that happens with a forced check on the
    already known announcement, or when Wizards touches the page days later
    (new lastmod, same URL - e.g. August 10 -> lastmod August 21). In that
    case send_ban_announcement_log() posts to the log channel only. A
    different URL is always "new", unlike the Event Schedule, where an
    in-place update of the same page is genuinely new content.
    """

    headers = {"User-Agent": "ClepshydraBot/1.0 (Discord Tournament Bot)"}
    timeout = aiohttp.ClientTimeout(total=60)

    state = _load_state()

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        current = await _fetch_sitemap_ban_urls(session)

        latest = _pick_latest(current)
        if latest is None:
            log("[BAN ANNOUNCEMENT] no announcement found in the sitemap")
            return []

        url, lastmod = latest

        already_seen = state.get("latest_url") == url and state.get("latest_lastmod") == lastmod
        if already_seen and not force:
            log(f"[BAN ANNOUNCEMENT] no change (latest: {url})")
            return []

        log(f"[BAN ANNOUNCEMENT] new/updated announcement: {url}")

        page_html = await _fetch_page_html(session, url)

        if page_html is None:
            # Fetch failed: leave the state untouched and retry on the next
            # run instead of marking it as seen.
            log(f"[BAN ANNOUNCEMENT] fetch failed for {url}, retrying on the next run")
            return []

        changes = parse_ban_announcement(page_html)

    notified_url = _notified_url(state)
    already_notified = notified_url == url
    if changes and not already_notified:
        # Marked as notified here already, before sending: same trade-off as
        # latest_url - a state saved before the Discord post doesn't resend
        # it if the post fails, but it can't repost it in a loop either.
        notified_url = url

    _save_state({"latest_url": url, "latest_lastmod": lastmod, "notified_url": notified_url})

    if changes is None:
        log(f"[BAN ANNOUNCEMENT] {url}: summary structure not recognized")
    else:
        log(f"[BAN ANNOUNCEMENT] {url}: {len(changes)} formats with changes")

    return [{"url": url, "lastmod": lastmod, "changes": changes, "already_notified": already_notified}]


async def periodic_ban_announcement_check_loop(
    bot=None,
    interval_seconds: int = _CHECK_INTERVAL_SECONDS,
) -> None:
    """Background task: checks the sitemap every 2 hours and notifies
    Discord of every new Banned and Restricted announcement. The first run
    starts right at startup, like the other periodic_*_loop in main.py."""

    while True:
        try:
            results = await check_ban_announcement_updates()

            if results and bot is not None:
                logger = bot.get_cog("Logger")
                if logger:
                    for result in results:
                        await send_ban_announcement_log(logger, result, user=None, forced=False)

        except Exception as e:
            log(f"[BAN ANNOUNCEMENT AUTO-CHECK] error: {e}")

        await asyncio.sleep(interval_seconds)


_FIELD_VALUE_LIMIT = 1024  # Discord limit for an embed field value


async def send_ban_announcement_log(logger, result: dict, user, forced: bool) -> None:
    """Posts to Discord (via the Logger cog) the outcome of checking a single
    Banned and Restricted announcement. Public because both the automatic
    loop and the manual admin command use it.

    Notify-only: it never writes to banned_cards (see docs/banlist-system.md
    - none of the official Wizards formats in these announcements matches
    this community's homebrew Artisan, so there is nothing to communicate
    about it). When the announcement has real changes, the embed is also
    posted to COMUNICATION_CHANNEL_ID (lazy import, like
    utils/permissions.py, to stay importable in tests without a full .env)
    besides the log channel - it concerns the whole community, not just
    staff. The community channel is public and @everyone gets pinged there:
    Logger.send_log()'s `community_title`/`community_info` build a
    dedicated Italian embed without the staff jargon ("Forced manual check",
    the user who invoked the command), which stays in the log channel's
    `info` - only the `fields` (cards banned/unbanned per format) are shared
    between the two, being genuine content for the community too. If
    result["already_notified"] is True (announcement already shared with the
    community, re-checked by hand or touched by Wizards) the post goes to the
    log channel only - see check_ban_announcement_updates()."""

    url = result["url"]
    changes = result["changes"]
    prefix = "Forced manual check" if forced else "Automatic check"

    if changes is None:
        await logger.send_log(
            level="WARN",
            event="BAN_ANNOUNCEMENT_UNPARSEABLE",
            user=user,
            info=(
                f"{prefix}: found a new Banned and Restricted Announcement on {url} but "
                f"the per-format summary was not recognized (the site structure may have "
                f"changed). A manual check is recommended."
            ),
        )
        return

    if not changes:
        await logger.send_log(
            level="INFO",
            event="BAN_ANNOUNCEMENT_NO_CHANGES",
            user=user,
            info=(f"{prefix}: new Banned and Restricted Announcement on {url}, no format changed this time."),
        )
        return

    fields = []
    for format_name, lines in changes.items():
        value = "\n".join(lines)
        if len(value) > _FIELD_VALUE_LIMIT:
            value = value[: _FIELD_VALUE_LIMIT - 1] + "…"
        fields.append({"name": format_name, "value": value, "inline": False})

    if result.get("already_notified", False):
        await logger.send_log(
            level="INFO",
            event="BAN_ANNOUNCEMENT_UPDATED",
            user=user,
            info=(
                f"{prefix}: Banned and Restricted Announcement re-checked — {url} "
                f"(already notified to the community, not reposted to the community channel)"
            ),
            fields=fields,
        )
        return

    from config.config import COMUNICATION_CHANNEL_ID

    lastmod_text = format_lastmod(result["lastmod"])

    await logger.send_log(
        level="INFO",
        event="BAN_ANNOUNCEMENT_UPDATED",
        user=user,
        info=f"{prefix}: new Banned and Restricted Announcement — {url}",
        fields=fields,
        extra_channel_id=COMUNICATION_CHANNEL_ID,
        community_title=f"📋 Nuovo Banned and Restricted Announcement — {lastmod_text}",
        community_info=f"Ecco cosa cambia nei formati ufficiali Magic — [leggi l'annuncio completo]({url})",
    )
