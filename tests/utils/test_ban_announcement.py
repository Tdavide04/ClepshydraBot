import asyncio
import json

import pytest

import utils.ban_announcement as ban_announcement


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Ogni test parte da uno stato pulito su disco e in cache, come
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

# Frammento realistico osservato dal vivo sulla pagina reale
# banned-and-restricted-august-10-2026: heading di formato seguito da un
# riepilogo <p style="padding-left: 30px;"> con <auto-card> e <br/> tra le
# voci, oppure il letterale "No changes".
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

NO_STRUCTURE_HTML = "<html><body><article><h1>Some Other Page</h1><p>niente qui</p></article></body></html>"

# Frammento realistico del sitemap: mix di annunci ban, pagine Event Schedule
# (da escludere) e pagine di prodotto totalmente estranee (da escludere).
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
        """Un annuncio interpretato correttamente ma senza modifiche in
        nessun formato e' un esito valido (nulla da segnalare), non un
        errore di parsing - va distinto da 'struttura non riconosciuta'."""
        changes = ban_announcement.parse_ban_announcement(ALL_NO_CHANGES_HTML)

        assert changes == {}

    def test_returns_none_when_no_format_heading_found(self):
        assert ban_announcement.parse_ban_announcement(NO_STRUCTURE_HTML) is None


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
        assert ANNOUNCEMENT_B_URL not in calls, "l'annuncio passato non va nemmeno scaricato"

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

        assert results == [], "lastmod invariato: non deve rifare il fetch della pagina"
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


class FakeLogger:
    def __init__(self):
        self.calls = []

    async def send_log(self, level, event, user=None, channel=None, info=None, fields=None, files=None):
        self.calls.append({
            "level": level, "event": event, "info": info,
            "fields": fields or [], "files": files or [],
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

    def test_no_changes_sends_a_plain_info_with_no_fields(self):
        logger = FakeLogger()
        result = {"url": ANNOUNCEMENT_A_URL, "lastmod": "x", "changes": {}}

        run(ban_announcement.send_ban_announcement_log(logger, result, user=None, forced=False))

        assert len(logger.calls) == 1
        assert logger.calls[0]["level"] == "INFO"
        assert logger.calls[0]["event"] == "BAN_ANNOUNCEMENT_NO_CHANGES"
        assert logger.calls[0]["fields"] == []

    def test_changes_are_posted_as_one_field_per_format(self):
        logger = FakeLogger()
        changes = {
            "Standard": ["Badgermole Cub is banned."],
            "Brawl": ["Some Card is banned.", "Other Card is unbanned."],
        }
        result = {"url": ANNOUNCEMENT_A_URL, "lastmod": "x", "changes": changes}

        run(ban_announcement.send_ban_announcement_log(logger, result, user=None, forced=False))

        assert len(logger.calls) == 1
        assert logger.calls[0]["level"] == "INFO"
        assert logger.calls[0]["event"] == "BAN_ANNOUNCEMENT_UPDATED"
        field_names = {f["name"] for f in logger.calls[0]["fields"]}
        assert field_names == {"Standard", "Brawl"}
        brawl_field = next(f for f in logger.calls[0]["fields"] if f["name"] == "Brawl")
        assert brawl_field["value"] == "Some Card is banned.\nOther Card is unbanned."
