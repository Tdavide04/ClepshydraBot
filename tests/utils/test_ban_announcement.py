import asyncio
import json

import pytest

import utils.ban_announcement as ban_announcement


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Every test starts from a clean state on disk and in cache, like
    isolated_state in test_arena_event_schedule.py."""
    monkeypatch.setattr(ban_announcement, "STATE_PATH", str(tmp_path / "ban_announcement_state.json"))
    monkeypatch.setattr(ban_announcement, "_state_cache", None)
    yield


def run(coro):
    return asyncio.run(coro)


def _install_fake_network(monkeypatch, sitemap: dict, pages: dict, calls: list):
    async def fake_sitemap(session):
        calls.append("sitemap")
        return dict(sitemap)

    async def fake_page(session, url):
        calls.append(url)
        return pages.get(url)

    monkeypatch.setattr(ban_announcement, "_fetch_sitemap_ban_urls", fake_sitemap)
    monkeypatch.setattr(ban_announcement, "_fetch_page_html", fake_page)


ANNOUNCEMENT_A_URL = "https://magic.wizards.com/en/news/announcements/banned-and-restricted-august-10-2026"
ANNOUNCEMENT_B_URL = "https://magic.wizards.com/en/news/announcements/banned-and-restricted-june-29-2026"

# Realistic fragment observed live on the real page
# banned-and-restricted-august-10-2026: a format heading followed by a
# <p style="padding-left: 30px;"> summary with <auto-card> and <br/> between
# the lines, or the literal "No changes".
VALID_ANNOUNCEMENT_HTML = """
<html><body><article>
<h2 id="Standard" style="scroll-margin-top: 70px;">Standard</h2>
<p>Written by Jadine Klomparens</p>
<p style="padding-left: 30px;"><auto-card>Badgermole Cub</auto-card> is banned.<br /><auto-card>Gran-Gran</auto-card> is banned.</p>
<p>Lots of prose analysis here that must not be extracted.</p>
<hr />
<h2 id="Pauper" style="scroll-margin-top: 70px;">Pauper</h2>
<p>Written by Gavin Verhey</p>
<p style="padding-left: 30px;">No changes</p>
<p>More prose that must not be extracted.</p>
<hr />
<h2 id="Alchemy" style="scroll-margin-top: 70px;">Alchemy</h2>
<p>Written by Dave Finseth</p>
<p style="padding-left: 30px;">No changes</p>
</article></body></html>
"""

ALL_NO_CHANGES_HTML = """
<html><body><article>
<h2 id="Standard" style="scroll-margin-top: 70px;">Standard</h2>
<p style="padding-left: 30px;">No changes</p>
<h2 id="Modern" style="scroll-margin-top: 70px;">Modern</h2>
<p style="padding-left: 30px;">No changes</p>
</article></body></html>
"""

NO_STRUCTURE_HTML = "<html><body><article><h1>Some Other Page</h1><p>nothing here</p></article></body></html>"

# Realistic sitemap fragment: a mix of ban announcements, Event Schedule
# pages (to exclude) and completely unrelated product pages (to exclude).
SAMPLE_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://magic.wizards.com/en/news/announcements/banned-and-restricted-august-10-2026</loc><lastmod>2026-08-21T18:02:33.573Z</lastmod></url>
<url><loc>https://magic.wizards.com/en/news/announcements/banned-and-restricted-june-29-2026</loc><lastmod>2026-07-01T17:53:16.017Z</lastmod></url>
<url><loc>https://magic.wizards.com/en/news/mtg-arena/the-hobbit-event-schedule</loc><lastmod>2026-09-02T16:05:08.364Z</lastmod></url>
<url><loc>https://magic.wizards.com/en/products/reality-fracture</loc><lastmod>2026-09-08T20:44:55.285Z</lastmod></url>
</urlset>
"""


class TestParseSitemapXml:

    def test_extracts_only_ban_announcement_urls_with_lastmod(self):
        found = ban_announcement._parse_sitemap_xml(SAMPLE_SITEMAP_XML)

        assert found == {
            ANNOUNCEMENT_A_URL: "2026-08-21T18:02:33.573Z",
            ANNOUNCEMENT_B_URL: "2026-07-01T17:53:16.017Z",
        }

    def test_ignores_event_schedule_and_unrelated_pages(self):
        found = ban_announcement._parse_sitemap_xml(SAMPLE_SITEMAP_XML)

        urls = set(found.keys())
        assert not any("event-schedule" in u for u in urls)
        assert not any("/products/" in u for u in urls)

    def test_malformed_xml_returns_empty_dict_instead_of_raising(self):
        assert ban_announcement._parse_sitemap_xml("<not valid xml") == {}


class TestParseBanAnnouncement:

    def test_extracts_only_formats_with_real_changes(self):
        changes = ban_announcement.parse_ban_announcement(VALID_ANNOUNCEMENT_HTML)

        assert changes == {
            "Standard": ["Badgermole Cub is banned.", "Gran-Gran is banned."],
        }

    def test_no_changes_formats_are_excluded_not_reported_as_empty_lines(self):
        changes = ban_announcement.parse_ban_announcement(VALID_ANNOUNCEMENT_HTML)

        assert "Pauper" not in changes
        assert "Alchemy" not in changes

    def test_does_not_extract_surrounding_prose(self):
        changes = ban_announcement.parse_ban_announcement(VALID_ANNOUNCEMENT_HTML)

        assert "Lots of prose analysis here that must not be extracted." not in changes["Standard"]

    def test_all_formats_with_no_changes_returns_empty_dict_not_none(self):
        """An announcement parsed correctly but with no change in any format
        is a valid outcome (nothing to report), not a parsing error - it must
        be told apart from 'structure not recognized'."""
        changes = ban_announcement.parse_ban_announcement(ALL_NO_CHANGES_HTML)

        assert changes == {}

    def test_returns_none_when_no_format_heading_found(self):
        assert ban_announcement.parse_ban_announcement(NO_STRUCTURE_HTML) is None


class TestFormatLastmod:

    def test_formats_an_iso8601_utc_timestamp_in_italian(self):
        formatted = ban_announcement.format_lastmod("2026-08-21T18:02:33.573Z")
        assert formatted == "21 Agosto 2026, 18:02 UTC"

    def test_returns_the_original_string_unchanged_on_unexpected_format(self):
        """A broken cosmetic detail must not make the notification fail -
        same 'degrade, don't crash' philosophy as the rest of the module."""
        assert ban_announcement.format_lastmod("not-a-timestamp") == "not-a-timestamp"


class TestPickLatest:

    def test_returns_the_entry_with_the_most_recent_lastmod(self):
        entries = {
            ANNOUNCEMENT_A_URL: "2026-08-21T18:02:33.573Z",
            ANNOUNCEMENT_B_URL: "2026-07-01T17:53:16.017Z",
        }
        assert ban_announcement._pick_latest(entries) == (ANNOUNCEMENT_A_URL, "2026-08-21T18:02:33.573Z")

    def test_returns_none_for_empty_input(self):
        assert ban_announcement._pick_latest({}) is None


class TestCheckBanAnnouncementUpdates:

    def test_first_check_reports_only_the_latest_announcement(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={
                ANNOUNCEMENT_A_URL: "2026-08-21T18:02:33.573Z",
                ANNOUNCEMENT_B_URL: "2026-07-01T17:53:16.017Z",
            },
            pages={ANNOUNCEMENT_A_URL: VALID_ANNOUNCEMENT_HTML, ANNOUNCEMENT_B_URL: VALID_ANNOUNCEMENT_HTML},
            calls=calls,
        )

        results = run(ban_announcement.check_ban_announcement_updates())

        assert [r["url"] for r in results] == [ANNOUNCEMENT_A_URL]
        assert ANNOUNCEMENT_B_URL not in calls, "the past announcement must not even be downloaded"

    def test_second_check_skips_when_latest_is_unchanged(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={ANNOUNCEMENT_A_URL: "2026-08-21T18:02:33.573Z"},
            pages={ANNOUNCEMENT_A_URL: VALID_ANNOUNCEMENT_HTML},
            calls=calls,
        )
        run(ban_announcement.check_ban_announcement_updates())

        calls.clear()
        results = run(ban_announcement.check_ban_announcement_updates())

        assert results == [], "lastmod unchanged: the page must not be fetched again"
        assert ANNOUNCEMENT_A_URL not in calls
        assert "sitemap" in calls

    def test_force_reprocesses_even_without_lastmod_change(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={ANNOUNCEMENT_A_URL: "2026-08-21T18:02:33.573Z"},
            pages={ANNOUNCEMENT_A_URL: VALID_ANNOUNCEMENT_HTML},
            calls=calls,
        )
        run(ban_announcement.check_ban_announcement_updates())

        calls.clear()
        results = run(ban_announcement.check_ban_announcement_updates(force=True))

        assert [r["url"] for r in results] == [ANNOUNCEMENT_A_URL]
        assert ANNOUNCEMENT_A_URL in calls

    def test_unparseable_page_is_reported_not_dropped(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={ANNOUNCEMENT_A_URL: "2026-08-21T18:02:33.573Z"},
            pages={ANNOUNCEMENT_A_URL: NO_STRUCTURE_HTML},
            calls=calls,
        )

        results = run(ban_announcement.check_ban_announcement_updates())

        assert len(results) == 1
        assert results[0]["changes"] is None
        with open(ban_announcement.STATE_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["latest_url"] == ANNOUNCEMENT_A_URL

    def test_failed_fetch_does_not_update_state(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={ANNOUNCEMENT_A_URL: "2026-08-21T18:02:33.573Z"},
            pages={},
            calls=calls,
        )

        results = run(ban_announcement.check_ban_announcement_updates())

        assert results == []
        import os
        assert not os.path.exists(ban_announcement.STATE_PATH)

    def test_first_announcement_with_changes_is_not_already_notified(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={ANNOUNCEMENT_A_URL: "2026-08-21T18:02:33.573Z"},
            pages={ANNOUNCEMENT_A_URL: VALID_ANNOUNCEMENT_HTML},
            calls=calls,
        )

        results = run(ban_announcement.check_ban_announcement_updates())

        assert results[0]["already_notified"] is False
        with open(ban_announcement.STATE_PATH, encoding="utf-8") as f:
            assert json.load(f)["notified_url"] == ANNOUNCEMENT_A_URL

    def test_forced_recheck_of_a_notified_announcement_is_already_notified(self, monkeypatch):
        """Regression 2026-10-12: a /forced_ban_announcement_check run while
        the sitemap didn't list the new announcement yet reposted the August
        one, already notified, to the community channel as if it were new."""
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={ANNOUNCEMENT_A_URL: "2026-08-21T18:02:33.573Z"},
            pages={ANNOUNCEMENT_A_URL: VALID_ANNOUNCEMENT_HTML},
            calls=calls,
        )
        run(ban_announcement.check_ban_announcement_updates())

        results = run(ban_announcement.check_ban_announcement_updates(force=True))

        assert results[0]["already_notified"] is True

    def test_lastmod_change_on_a_notified_announcement_is_already_notified(self, monkeypatch):
        """Wizards touches announcements days later (August 10 -> lastmod
        August 21): a new lastmod on the same URL is not a new announcement."""
        calls = []
        sitemap = {ANNOUNCEMENT_A_URL: "2026-08-10T16:00:00.000Z"}
        _install_fake_network(monkeypatch, sitemap=sitemap, pages={ANNOUNCEMENT_A_URL: VALID_ANNOUNCEMENT_HTML}, calls=calls)
        run(ban_announcement.check_ban_announcement_updates())

        sitemap[ANNOUNCEMENT_A_URL] = "2026-08-21T18:02:33.573Z"
        results = run(ban_announcement.check_ban_announcement_updates())

        assert [r["url"] for r in results] == [ANNOUNCEMENT_A_URL], "the edit must still be re-read and logged"
        assert results[0]["already_notified"] is True

    def test_new_url_after_a_notified_one_is_not_already_notified(self, monkeypatch):
        calls = []
        sitemap = {ANNOUNCEMENT_B_URL: "2026-07-01T17:53:16.017Z"}
        pages = {ANNOUNCEMENT_A_URL: VALID_ANNOUNCEMENT_HTML, ANNOUNCEMENT_B_URL: VALID_ANNOUNCEMENT_HTML}
        _install_fake_network(monkeypatch, sitemap=sitemap, pages=pages, calls=calls)
        run(ban_announcement.check_ban_announcement_updates())

        sitemap[ANNOUNCEMENT_A_URL] = "2026-08-21T18:02:33.573Z"
        results = run(ban_announcement.check_ban_announcement_updates())

        assert results[0]["url"] == ANNOUNCEMENT_A_URL
        assert results[0]["already_notified"] is False

    def test_announcement_without_changes_is_not_marked_as_notified(self, monkeypatch):
        """Nothing was posted to the community: if a later edit adds real
        changes, they must be announced."""
        calls = []
        pages = {ANNOUNCEMENT_A_URL: ALL_NO_CHANGES_HTML}
        sitemap = {ANNOUNCEMENT_A_URL: "2026-08-10T16:00:00.000Z"}
        _install_fake_network(monkeypatch, sitemap=sitemap, pages=pages, calls=calls)
        run(ban_announcement.check_ban_announcement_updates())

        pages[ANNOUNCEMENT_A_URL] = VALID_ANNOUNCEMENT_HTML
        sitemap[ANNOUNCEMENT_A_URL] = "2026-08-21T18:02:33.573Z"
        results = run(ban_announcement.check_ban_announcement_updates())

        assert results[0]["already_notified"] is False

    def test_legacy_state_without_notified_url_treats_latest_url_as_notified(self, monkeypatch):
        """The production state before 3.5.3 has only latest_url/latest_lastmod:
        the announcement already processed must not be reposted, a new one must."""
        with open(ban_announcement.STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"latest_url": ANNOUNCEMENT_B_URL, "latest_lastmod": "2026-07-01T17:53:16.017Z"}, f)

        calls = []
        sitemap = {ANNOUNCEMENT_B_URL: "2026-07-01T17:53:16.017Z"}
        pages = {ANNOUNCEMENT_A_URL: VALID_ANNOUNCEMENT_HTML, ANNOUNCEMENT_B_URL: VALID_ANNOUNCEMENT_HTML}
        _install_fake_network(monkeypatch, sitemap=sitemap, pages=pages, calls=calls)

        forced = run(ban_announcement.check_ban_announcement_updates(force=True))
        assert forced[0]["already_notified"] is True

        sitemap[ANNOUNCEMENT_A_URL] = "2026-08-21T18:02:33.573Z"
        results = run(ban_announcement.check_ban_announcement_updates())
        assert results[0]["url"] == ANNOUNCEMENT_A_URL
        assert results[0]["already_notified"] is False


class FakeLogger:
    def __init__(self):
        self.calls = []

    async def send_log(self, level, event, user=None, channel=None, info=None, fields=None, files=None,
                        extra_channel_id=None, community_title=None, community_info=None):
        self.calls.append({
            "level": level, "event": event, "info": info,
            "fields": fields or [], "files": files or [],
            "extra_channel_id": extra_channel_id,
            "community_title": community_title, "community_info": community_info,
        })


class TestSendBanAnnouncementLog:

    def test_unparseable_announcement_sends_a_single_warn(self):
        logger = FakeLogger()
        result = {"url": ANNOUNCEMENT_A_URL, "lastmod": "x", "changes": None}

        run(ban_announcement.send_ban_announcement_log(logger, result, user=None, forced=False))

        assert len(logger.calls) == 1
        assert logger.calls[0]["level"] == "WARN"
        assert logger.calls[0]["event"] == "BAN_ANNOUNCEMENT_UNPARSEABLE"
        assert logger.calls[0]["fields"] == []
        assert logger.calls[0]["extra_channel_id"] is None, "only staff must see the unparseable WARNs"

    def test_no_changes_sends_a_plain_info_with_no_fields(self):
        logger = FakeLogger()
        result = {"url": ANNOUNCEMENT_A_URL, "lastmod": "x", "changes": {}}

        run(ban_announcement.send_ban_announcement_log(logger, result, user=None, forced=False))

        assert len(logger.calls) == 1
        assert logger.calls[0]["level"] == "INFO"
        assert logger.calls[0]["event"] == "BAN_ANNOUNCEMENT_NO_CHANGES"
        assert logger.calls[0]["fields"] == []
        assert logger.calls[0]["extra_channel_id"] is None, "nothing to tell the community if nothing changes"

    def test_changes_are_posted_as_one_field_per_format_and_to_the_community_channel(self, monkeypatch):
        import config.config as config_module
        monkeypatch.setattr(config_module, "COMUNICATION_CHANNEL_ID", 999)

        logger = FakeLogger()
        changes = {
            "Standard": ["Badgermole Cub is banned."],
            "Brawl": ["Some Card is banned.", "Other Card is unbanned."],
        }
        result = {"url": ANNOUNCEMENT_A_URL, "lastmod": "2026-08-21T18:02:33.573Z", "changes": changes}

        run(ban_announcement.send_ban_announcement_log(logger, result, user=None, forced=False))

        assert len(logger.calls) == 1
        assert logger.calls[0]["level"] == "INFO"
        assert logger.calls[0]["event"] == "BAN_ANNOUNCEMENT_UPDATED"
        assert logger.calls[0]["extra_channel_id"] == 999
        assert "banlist" not in logger.calls[0]["info"].lower(), (
            "this community's homebrew Artisan is not affected by these announcements, "
            "so the message must not mention it"
        )
        field_names = {f["name"] for f in logger.calls[0]["fields"]}
        assert field_names == {"Standard", "Brawl"}
        brawl_field = next(f for f in logger.calls[0]["fields"] if f["name"] == "Brawl")
        assert brawl_field["value"] == "Some Card is banned.\nOther Card is unbanned."

        # The community channel is public (@everyone gets pinged): its
        # dedicated embed must contain neither staff jargon ("Forced manual
        # check"/"Automatic check") nor the raw URL without context - only a
        # clean title and text, distinct from the log channel's `info`.
        community_title = logger.calls[0]["community_title"]
        community_info = logger.calls[0]["community_info"]
        assert community_title and "banned" in community_title.lower()
        assert "check" not in community_info.lower()
        assert ANNOUNCEMENT_A_URL in community_info

        # The announcement's date/time (from the formatted lastmod) in the title.
        assert community_title == "📋 Nuovo Banned and Restricted Announcement — 21 Agosto 2026, 18:02 UTC"

    def test_already_notified_changes_go_to_the_log_channel_only(self, monkeypatch):
        import config.config as config_module
        monkeypatch.setattr(config_module, "COMUNICATION_CHANNEL_ID", 999)

        logger = FakeLogger()
        result = {
            "url": ANNOUNCEMENT_A_URL, "lastmod": "2026-08-21T18:02:33.573Z",
            "changes": {"Standard": ["Badgermole Cub is banned."]}, "already_notified": True,
        }

        run(ban_announcement.send_ban_announcement_log(logger, result, user=None, forced=True))

        assert len(logger.calls) == 1
        assert logger.calls[0]["event"] == "BAN_ANNOUNCEMENT_UPDATED"
        assert logger.calls[0]["extra_channel_id"] is None, "already shared with the community, no repost"
        assert [f["name"] for f in logger.calls[0]["fields"]] == ["Standard"]
        assert "already notified" in logger.calls[0]["info"]
