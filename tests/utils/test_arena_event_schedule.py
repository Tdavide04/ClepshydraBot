import asyncio
import json

import pytest

import utils.arena_event_schedule as arena_event_schedule


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Ogni test parte da uno stato pulito su disco e in cache, come
    isolated_overrides in test_arena_overrides.py."""
    monkeypatch.setattr(arena_event_schedule, "STATE_PATH", str(tmp_path / "arena_event_schedule_state.json"))
    monkeypatch.setattr(arena_event_schedule, "_state_cache", None)
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

    monkeypatch.setattr(arena_event_schedule, "_fetch_sitemap_event_schedule_urls", fake_sitemap)
    monkeypatch.setattr(arena_event_schedule, "_fetch_page_html", fake_page)


SET_A_URL = "https://magic.wizards.com/en/news/mtg-arena/set-a-event-schedule"
SET_B_URL = "https://magic.wizards.com/en/news/mtg-arena/set-b-event-schedule"

# Frammento realistico della sezione "Full Event Calendar" osservata sulle
# pagine reali (the-hobbit-event-schedule, teenage-mutant-ninja-turtles-event-schedule):
# heading bare (nessun attributo CSS, a differenza delle card di navigazione
# laterale) seguito immediatamente da una <ul><li>.
VALID_CALENDAR_HTML = """
<html><body><article>
<h2>Full Event Calendar</h2>

<h3>Premier Draft</h3>
<ul>
	<li>August 11–September 29: <i>Magic: The Gathering</i> | <i>Set A</i></li>
</ul>

<h3>Quick Draft</h3>
<ul>
	<li>August 11–19: <i>Duskmourn: House of Horror</i></li>
	<li>August 20–30: <i>Set A</i></li>
</ul>
</article>
<aside><h3 class="css-blB8m css-Km4tb">Not part of the calendar</h3>
<ul><li>Deve essere ignorato: sta fuori da &lt;/article&gt;</li></ul>
</aside>
</body></html>
"""

NO_CALENDAR_HTML = "<html><body><article><h2>Some Other Page</h2><p>niente qui</p></article></body></html>"

# Frammento realistico del sitemap reale (magic.wizards.com/en/sitemap.xml):
# mix di pagine event-schedule, post announcements settimanali (da escludere)
# e pagine di prodotto totalmente estranee (da escludere).
SAMPLE_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://magic.wizards.com/en/news/mtg-arena/the-hobbit-event-schedule</loc><lastmod>2026-09-02T16:05:08.364Z</lastmod></url>
<url><loc>https://magic.wizards.com/en/news/mtg-arena/teenage-mutant-ninja-turtles-event-schedule</loc><lastmod>2026-03-02T18:00:08.627Z</lastmod></url>
<url><loc>https://magic.wizards.com/en/news/mtg-arena/announcements-september-8-2026</loc><lastmod>2026-09-08T17:00:10.023Z</lastmod></url>
<url><loc>https://magic.wizards.com/en/products/reality-fracture</loc><lastmod>2026-09-08T20:44:55.285Z</lastmod></url>
</urlset>
"""


class TestParseSitemapXml:

    def test_extracts_only_event_schedule_urls_with_lastmod(self):
        found = arena_event_schedule._parse_sitemap_xml(SAMPLE_SITEMAP_XML)

        assert found == {
            "https://magic.wizards.com/en/news/mtg-arena/the-hobbit-event-schedule": "2026-09-02T16:05:08.364Z",
            "https://magic.wizards.com/en/news/mtg-arena/teenage-mutant-ninja-turtles-event-schedule": "2026-03-02T18:00:08.627Z",
        }

    def test_ignores_weekly_announcements_and_unrelated_pages(self):
        found = arena_event_schedule._parse_sitemap_xml(SAMPLE_SITEMAP_XML)

        urls = set(found.keys())
        assert not any("announcements-" in u for u in urls)
        assert not any("/products/" in u for u in urls)

    def test_malformed_xml_returns_empty_dict_instead_of_raising(self):
        assert arena_event_schedule._parse_sitemap_xml("<not valid xml") == {}


class TestParseFullEventCalendar:

    def test_extracts_categories_and_entries(self):
        categories = arena_event_schedule.parse_full_event_calendar(VALID_CALENDAR_HTML)

        assert categories is not None
        assert categories["Premier Draft"] == ["August 11–September 29: Magic: The Gathering | Set A"]
        assert categories["Quick Draft"] == [
            "August 11–19: Duskmourn: House of Horror",
            "August 20–30: Set A",
        ]

    def test_ignores_content_outside_article_boundary(self):
        categories = arena_event_schedule.parse_full_event_calendar(VALID_CALENDAR_HTML)

        assert "Not part of the calendar" not in categories

    def test_returns_none_when_calendar_heading_missing(self):
        assert arena_event_schedule.parse_full_event_calendar(NO_CALENDAR_HTML) is None


class TestCheckEventScheduleUpdates:

    def test_first_check_processes_every_known_page(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03", SET_B_URL: "2026-06-15"},
            pages={SET_A_URL: VALID_CALENDAR_HTML, SET_B_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )

        results = run(arena_event_schedule.check_event_schedule_updates())

        urls_seen = {r["url"] for r in results}
        assert urls_seen == {SET_A_URL, SET_B_URL}
        assert all(r["categories"] is not None for r in results)

    def test_second_check_skips_unchanged_lastmod(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03"},
            pages={SET_A_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        run(arena_event_schedule.check_event_schedule_updates())

        calls.clear()
        results = run(arena_event_schedule.check_event_schedule_updates())

        assert results == [], "lastmod invariato: non deve rifare il fetch della pagina"
        assert SET_A_URL not in calls
        assert "sitemap" in calls, "il sitemap va comunque ricontrollato per sapere se qualcosa e' cambiato"

    def test_changed_lastmod_triggers_reprocessing(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03"},
            pages={SET_A_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        run(arena_event_schedule.check_event_schedule_updates())

        # Simula l'aggiornamento in-place osservato su the-hobbit-event-schedule
        # (pubblicata il 3 agosto, lastmod aggiornato al 2 settembre).
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-09-02"},
            pages={SET_A_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        calls.clear()
        results = run(arena_event_schedule.check_event_schedule_updates())

        assert [r["url"] for r in results] == [SET_A_URL]
        assert SET_A_URL in calls

        with open(arena_event_schedule.STATE_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["known"][SET_A_URL] == "2026-09-02"

    def test_force_reprocesses_even_without_lastmod_change(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03"},
            pages={SET_A_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        run(arena_event_schedule.check_event_schedule_updates())

        calls.clear()
        results = run(arena_event_schedule.check_event_schedule_updates(force=True))

        assert [r["url"] for r in results] == [SET_A_URL]
        assert SET_A_URL in calls

    def test_unparseable_page_is_reported_not_dropped(self, monkeypatch):
        """Se la sezione 'Full Event Calendar' non viene trovata, il risultato
        deve comunque comparire con categories=None (cosi' il chiamante puo'
        segnalarlo), non essere silenziosamente scartato."""
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03"},
            pages={SET_A_URL: NO_CALENDAR_HTML},
            calls=calls,
        )

        results = run(arena_event_schedule.check_event_schedule_updates())

        assert len(results) == 1
        assert results[0]["categories"] is None
        # Anche se non interpretabile, lo stato va comunque aggiornato per non
        # ritentare la stessa pagina invariata ad ogni giro.
        with open(arena_event_schedule.STATE_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["known"][SET_A_URL] == "2026-08-03"

    def test_failed_fetch_does_not_update_state(self, monkeypatch):
        """Se il fetch della pagina fallisce (torna None), non va marcata come
        vista: ci si deve riprovare al prossimo giro."""
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03"},
            pages={},  # nessuna risposta -> _fetch_page_html restituisce None
            calls=calls,
        )

        results = run(arena_event_schedule.check_event_schedule_updates())

        assert results == []
        import os
        assert not os.path.exists(arena_event_schedule.STATE_PATH)
