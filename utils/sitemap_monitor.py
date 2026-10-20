"""
sitemap_monitor.py

Logic shared by the monitors that follow Wizards pages through the standard
XML sitemap of magic.wizards.com (utils/arena_event_schedule.py and
utils/ban_announcement.py): both fetch the same sitemap.xml every 2 hours,
pick the newest page of interest by `lastmod` (Wizards never removes past
pages from the sitemap, so several always coexist) and keep a "last page
seen" state in a local JSON file with atomic writes. Extracted here after the
second monitor (ban_announcement.py) duplicated this part byte for byte from
the first - URL filtering and page content parsing stay in each module, the
only part that genuinely differs between the two (different URL patterns and
HTML structure).
"""

import json
import os

import aiohttp

# Re-exported: both monitors import it from here (see utils/console.py).
from utils.console import log  # noqa: F401

SITEMAP_URL = "https://magic.wizards.com/en/sitemap.xml"

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Both monitors check the sitemap every 2 hours: a cheap GET on a static
# file (~660 KB), while the content that matters (a new Event Schedule page
# or a new Banned and Restricted Announcement) changes far less often -
# polling often costs almost nothing and lowers the latency with which the
# community is informed. It was 24h until 3.5.3: on 2026-10-12 the October
# Banned and Restricted was not in the sitemap yet (Wizards serves it with
# Cache-Control max-age ~1h and regenerates it after the article is
# published) at the time of the daily check, and the next run would have
# come almost 24h later.
_CHECK_INTERVAL_SECONDS = 2 * 60 * 60


def load_json_state(path: str, default: dict) -> dict:
    """Loads a JSON dict from disk, or a copy of `default` if the file
    doesn't exist yet (first run on a new machine)."""

    if not os.path.exists(path):
        return dict(default)

    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json_state(path: str, data: dict) -> None:
    """Atomic write (`.tmp` file + `os.replace`): a crash mid-save leaves
    the previous state intact instead of a corrupted/truncated JSON."""

    os.makedirs(os.path.dirname(path), exist_ok=True)

    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp_path, path)


def pick_latest_by_lastmod(entries: dict[str, str]) -> tuple[str, str] | None:
    """Among the pages found in the sitemap, returns the one with the newest
    `lastmod`. lastmod values are fixed-width ISO-8601 timestamps (e.g.
    '2026-09-02T16:05:08.364Z'), so lexicographic string comparison matches
    chronological order, with no date parsing needed."""

    if not entries:
        return None

    return max(entries.items(), key=lambda item: item[1])


async def fetch_sitemap_xml(session: aiohttp.ClientSession) -> str | None:
    """Fetches the XML body of sitemap.xml, or None if the request fails -
    the caller decides how to treat its absence (both monitors treat it as
    'no page found', not as a fatal error)."""

    async with session.get(SITEMAP_URL) as response:
        if response.status != 200:
            log(f"[SITEMAP FAIL] {SITEMAP_URL} -> {response.status}")
            return None
        return await response.text()


async def fetch_page_html(session: aiohttp.ClientSession, url: str, log_prefix: str) -> str | None:
    """Generic GET of a single page. `log_prefix` tells apart, in the
    console, which monitor produced a failure (e.g. 'EVENT SCHEDULE',
    'BAN ANNOUNCEMENT')."""

    async with session.get(url) as response:
        if response.status != 200:
            log(f"[{log_prefix} FETCH FAIL] {url} -> {response.status}")
            return None
        return await response.text()
