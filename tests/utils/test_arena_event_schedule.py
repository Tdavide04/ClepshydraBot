import asyncio
import json
from datetime import date

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

# Regressione 2026-09-21: reality-fracture-event-schedule ha iniziato a
# pubblicare l'heading "Full Event Calendar" CON attributi
# (id="FRACalendar" style="scroll-margin-top: 70px;"), diverso dal bare
# <h2> di tutte le pagine osservate finora - ha fatto scattare in produzione
# un WARN ARENA_EVENT_SCHEDULE_UNPARSEABLE per un falso positivo (drift
# minimo, non una vera mancanza della sezione).
ATTRIBUTED_CALENDAR_HEADING_HTML = """
<html><body><article>
<h2 id="FRACalendar" style="scroll-margin-top: 70px;">Full Event Calendar</h2>

<h3>Premier Draft</h3>
<ul>
	<li>September 29–November 9: <i>Reality Fracture</i></li>
</ul>
</article>
</body></html>
"""

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

    def test_recognizes_the_calendar_heading_even_with_attributes(self):
        """Regressione: l'heading 'Full Event Calendar' puo' avere
        attributi (id/style) come su reality-fracture-event-schedule, non
        solo il bare <h2> delle pagine precedenti."""
        categories = arena_event_schedule.parse_full_event_calendar(ATTRIBUTED_CALENDAR_HEADING_HTML)

        assert categories is not None
        assert categories["Premier Draft"] == ["September 29–November 9: Reality Fracture"]


class TestParseEventEntry:

    def test_parses_range_spanning_two_months(self):
        parsed = arena_event_schedule.parse_event_entry(
            "August 11–September 29: Magic: The Gathering | The Hobbit"
        )
        assert parsed == {
            "start_month": 8, "start_day": 11,
            "end_month": 9, "end_day": 29,
            "name": "Magic: The Gathering | The Hobbit",
        }

    def test_parses_range_within_a_single_month_without_repeating_month_name(self):
        parsed = arena_event_schedule.parse_event_entry(
            "August 11–19: Duskmourn: House of Horror"
        )
        assert parsed["start_month"] == 8
        assert parsed["end_month"] == 8
        assert parsed["start_day"] == 11
        assert parsed["end_day"] == 19
        # Il nome puo' contenere altri ':' oltre a quello che separa la data
        assert parsed["name"] == "Duskmourn: House of Horror"

    def test_accepts_plain_hyphen_as_well_as_en_dash(self):
        parsed = arena_event_schedule.parse_event_entry("August 11-19: Set")
        assert parsed is not None

    def test_returns_none_for_text_without_a_recognizable_date(self):
        assert arena_event_schedule.parse_event_entry("Evento senza data") is None


class TestBuildMonthCalendar:

    def test_splits_a_multi_month_range_at_month_boundaries(self):
        categories = {
            "Premier Draft": ["August 11–September 29: The Hobbit"],
        }
        result = arena_event_schedule.build_month_calendar(
            categories, reference_date=date(2026, 9, 15)
        )

        assert result[(2026, 8)]["Premier Draft"] == [(11, 31, "The Hobbit")]
        assert result[(2026, 9)]["Premier Draft"] == [(1, 29, "The Hobbit")]

    def test_single_month_range_is_not_split(self):
        categories = {"Quick Draft": ["August 11–19: Duskmourn"]}
        result = arena_event_schedule.build_month_calendar(
            categories, reference_date=date(2026, 9, 15)
        )

        assert list(result.keys()) == [(2026, 8)]
        assert result[(2026, 8)]["Quick Draft"] == [(11, 19, "Duskmourn")]

    def test_unparseable_entry_is_silently_excluded(self):
        categories = {"Quick Draft": ["Evento senza data", "August 11–19: Duskmourn"]}
        result = arena_event_schedule.build_month_calendar(
            categories, reference_date=date(2026, 9, 15)
        )

        assert result[(2026, 8)]["Quick Draft"] == [(11, 19, "Duskmourn")]

    def test_range_crossing_december_into_january_bumps_the_year(self):
        categories = {"Quick Draft": ["December 28–January 4: New Year Set"]}
        result = arena_event_schedule.build_month_calendar(
            categories, reference_date=date(2026, 12, 1)
        )

        assert result[(2026, 12)]["Quick Draft"] == [(28, 31, "New Year Set")]
        assert result[(2027, 1)]["Quick Draft"] == [(1, 4, "New Year Set")]

    def test_entry_referencing_january_while_checking_in_december_is_next_year(self):
        """Una voce (es. Flashback) che ricade a Gennaio mentre il check
        avviene a Dicembre appartiene all'anno prossimo, non a uno gia'
        passato di 11 mesi - copre l'euristica di _infer_start_year."""
        categories = {"Quick Draft": ["January 5–11: Some Set"]}
        result = arena_event_schedule.build_month_calendar(
            categories, reference_date=date(2026, 12, 20)
        )

        assert list(result.keys()) == [(2027, 1)]

    def test_recent_past_month_stays_in_the_current_year(self):
        """Una voce Flashback che si riferisce a un mese recente (non
        undici mesi indietro) deve restare nell'anno corrente, non essere
        spinta erroneamente all'anno prossimo."""
        categories = {"Flashback Premier Draft": ["August 25–September 7: LOTR"]}
        result = arena_event_schedule.build_month_calendar(
            categories, reference_date=date(2026, 9, 15)
        )

        assert (2026, 8) in result
        assert (2027, 8) not in result

    def test_no_parseable_entries_returns_empty_dict(self):
        categories = {"Quick Draft": ["Evento senza data"]}
        result = arena_event_schedule.build_month_calendar(
            categories, reference_date=date(2026, 9, 15)
        )
        assert result == {}


class TestExtractSetNameFromUrl:

    def test_strips_the_event_schedule_suffix_and_title_cases_words(self):
        url = "https://magic.wizards.com/en/news/mtg-arena/the-hobbit-event-schedule"
        assert arena_event_schedule.extract_set_name_from_url(url) == "The Hobbit"

    def test_handles_a_trailing_slash(self):
        url = "https://magic.wizards.com/en/news/mtg-arena/duskmourn-event-schedule/"
        assert arena_event_schedule.extract_set_name_from_url(url) == "Duskmourn"


class TestFormatPeriodCovered:

    def test_returns_none_for_an_empty_calendar(self):
        assert arena_event_schedule.format_period_covered({}) is None

    def test_single_month_range_has_no_repeated_year(self):
        categories = {"Quick Draft": ["August 11-19: Duskmourn"]}
        month_calendar = arena_event_schedule.build_month_calendar(
            categories, reference_date=date(2026, 9, 15)
        )
        assert arena_event_schedule.format_period_covered(month_calendar) == "11 Agosto - 19 Agosto 2026"

    def test_multi_month_range_spans_both_months(self):
        categories = {"Premier Draft": ["August 11-September 29: The Hobbit"]}
        month_calendar = arena_event_schedule.build_month_calendar(
            categories, reference_date=date(2026, 9, 15)
        )
        assert arena_event_schedule.format_period_covered(month_calendar) == "11 Agosto - 29 Settembre 2026"

    def test_range_crossing_into_next_year_shows_both_years(self):
        categories = {"Quick Draft": ["December 28-January 4: New Year Set"]}
        month_calendar = arena_event_schedule.build_month_calendar(
            categories, reference_date=date(2026, 12, 1)
        )
        assert arena_event_schedule.format_period_covered(month_calendar) == "28 Dicembre 2026 - 4 Gennaio 2027"

    def test_covers_the_full_span_across_multiple_categories(self):
        """Il periodo deve riflettere l'intervallo piu' ampio tra TUTTE le
        categorie, non solo la prima incontrata."""
        categories = {
            "Quick Draft": ["September 1-7: Secrets of Strixhaven"],
            "Premier Draft": ["August 11-19: Duskmourn"],
        }
        month_calendar = arena_event_schedule.build_month_calendar(
            categories, reference_date=date(2026, 9, 15)
        )
        assert arena_event_schedule.format_period_covered(month_calendar) == "11 Agosto - 7 Settembre 2026"


class TestPickLatest:

    def test_returns_the_entry_with_the_most_recent_lastmod(self):
        entries = {SET_A_URL: "2026-08-03T00:00:00Z", SET_B_URL: "2026-06-15T00:00:00Z"}
        assert arena_event_schedule._pick_latest(entries) == (SET_A_URL, "2026-08-03T00:00:00Z")

    def test_returns_none_for_empty_input(self):
        assert arena_event_schedule._pick_latest({}) is None


class TestCheckEventScheduleUpdates:

    def test_first_check_reports_only_the_latest_page_not_older_ones(self, monkeypatch):
        """Regressione diretta per il flood segnalato in produzione: al primo
        avvio su una macchina nuova (stato vuoto), il sitemap conteneva 4
        pagine Event Schedule ancora online (Wizards non rimuove quelle dei
        set passati) e venivano notificate tutte e 4 insieme. Deve arrivarne
        una sola: quella del set attualmente attivo (lastmod piu' recente)."""
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={
                SET_A_URL: "2026-08-03T00:00:00Z",  # set attivo
                SET_B_URL: "2026-06-15T00:00:00Z",  # set concluso, ancora sul sitemap
            },
            pages={SET_A_URL: VALID_CALENDAR_HTML, SET_B_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )

        results = run(arena_event_schedule.check_event_schedule_updates())

        assert [r["url"] for r in results] == [SET_A_URL]
        assert SET_B_URL not in calls, "la pagina del set concluso non va nemmeno scaricata"

    def test_second_check_skips_when_latest_is_unchanged(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03T00:00:00Z"},
            pages={SET_A_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        run(arena_event_schedule.check_event_schedule_updates())

        calls.clear()
        results = run(arena_event_schedule.check_event_schedule_updates())

        assert results == [], "lastmod invariato: non deve rifare il fetch della pagina"
        assert SET_A_URL not in calls
        assert "sitemap" in calls, "il sitemap va comunque ricontrollato per sapere se qualcosa e' cambiato"

    def test_changed_lastmod_on_the_latest_page_triggers_reprocessing(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03T00:00:00Z"},
            pages={SET_A_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        run(arena_event_schedule.check_event_schedule_updates())

        # Simula l'aggiornamento in-place osservato su the-hobbit-event-schedule
        # (pubblicata il 3 agosto, lastmod aggiornato al 2 settembre).
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-09-02T00:00:00Z"},
            pages={SET_A_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        calls.clear()
        results = run(arena_event_schedule.check_event_schedule_updates())

        assert [r["url"] for r in results] == [SET_A_URL]
        assert SET_A_URL in calls

        with open(arena_event_schedule.STATE_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["latest_lastmod"] == "2026-09-02T00:00:00Z"

    def test_a_newer_page_overtakes_the_previous_latest(self, monkeypatch):
        """Se esce un nuovo set con lastmod piu' recente di quello finora
        noto, deve diventare lui il 'latest' - anche se il lastmod della
        vecchia pagina non e' cambiato."""
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03T00:00:00Z"},
            pages={SET_A_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        run(arena_event_schedule.check_event_schedule_updates())

        _install_fake_network(
            monkeypatch,
            sitemap={
                SET_A_URL: "2026-08-03T00:00:00Z",  # invariato
                SET_B_URL: "2026-09-05T00:00:00Z",  # nuovo set, piu' recente
            },
            pages={SET_A_URL: VALID_CALENDAR_HTML, SET_B_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        calls.clear()
        results = run(arena_event_schedule.check_event_schedule_updates())

        assert [r["url"] for r in results] == [SET_B_URL]
        assert SET_A_URL not in calls

    def test_force_reprocesses_even_without_lastmod_change(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03T00:00:00Z"},
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
            sitemap={SET_A_URL: "2026-08-03T00:00:00Z"},
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
        assert on_disk["latest_url"] == SET_A_URL

    def test_failed_fetch_does_not_update_state(self, monkeypatch):
        """Se il fetch della pagina fallisce (torna None), non va marcata come
        vista: ci si deve riprovare al prossimo giro."""
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03T00:00:00Z"},
            pages={},  # nessuna risposta -> _fetch_page_html restituisce None
            calls=calls,
        )

        results = run(arena_event_schedule.check_event_schedule_updates())

        assert results == []
        import os
        assert not os.path.exists(arena_event_schedule.STATE_PATH)


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


class TestSendEventScheduleLog:

    def test_unparseable_page_sends_a_single_warn_with_no_files(self):
        logger = FakeLogger()
        result = {"url": SET_A_URL, "lastmod": "2026-08-03T00:00:00Z", "categories": None}

        run(arena_event_schedule.send_event_schedule_log(logger, result, user=None, forced=False))

        assert len(logger.calls) == 1
        assert logger.calls[0]["level"] == "WARN"
        assert logger.calls[0]["event"] == "ARENA_EVENT_SCHEDULE_UNPARSEABLE"
        assert logger.calls[0]["files"] == []
        assert logger.calls[0]["extra_channel_id"] is None, "un parse fallito e' rumore da staff, non da community"

    def test_categories_without_parseable_dates_send_a_warn_with_no_files(self):
        """Le categorie sono state interpretate (categories non e' None) ma
        nessuna voce segue il formato data atteso: build_month_calendar()
        torna vuoto, e non c'e' nulla da disegnare - deve arrivare un WARN
        distinto invece di un'immagine vuota o un errore."""
        logger = FakeLogger()
        categories = {"Premier Draft": ["Evento senza data riconoscibile"]}
        result = {"url": SET_A_URL, "lastmod": "x", "categories": categories}

        run(arena_event_schedule.send_event_schedule_log(logger, result, user=None, forced=False))

        assert len(logger.calls) == 1
        assert logger.calls[0]["level"] == "WARN"
        assert logger.calls[0]["event"] == "ARENA_EVENT_SCHEDULE_NO_DATES"
        assert logger.calls[0]["files"] == []
        assert logger.calls[0]["extra_channel_id"] is None, "nessuna data riconosciuta e' rumore da staff, non da community"

    def test_valid_categories_attach_one_image_per_month_and_post_to_the_community_channel(self, monkeypatch):
        """Sostituisce il vecchio design a campi embed di testo: un'immagine
        calendario per mese coinvolto, allegata allo stesso messaggio INFO,
        invece di descrivere gli eventi a parole. Un aggiornamento reale va
        anche nel canale community (extra_channel_id), a differenza dei due
        WARN sopra."""
        import config.config as config_module
        monkeypatch.setattr(config_module, "COMUNICATION_CHANNEL_ID", 999)

        logger = FakeLogger()
        categories = {
            "Premier Draft": ["August 11-19: Duskmourn: House of Horror"],
            "Quick Draft": ["September 1-7: Secrets of Strixhaven"],
        }
        result = {"url": SET_A_URL, "lastmod": "x", "categories": categories}

        run(arena_event_schedule.send_event_schedule_log(logger, result, user=None, forced=False))

        # Stesso default (nessun reference_date esplicito) usato dal codice
        # sotto test, cosi' l'aspettativa non dipende dalla data reale in
        # cui gira il test.
        expected_months = arena_event_schedule.build_month_calendar(categories)

        assert len(logger.calls) == 1
        assert logger.calls[0]["level"] == "INFO"
        assert logger.calls[0]["event"] == "ARENA_EVENT_SCHEDULE_UPDATED"
        assert len(logger.calls[0]["files"]) == len(expected_months)
        assert all(f.filename.startswith("calendario_") for f in logger.calls[0]["files"])
        assert logger.calls[0]["extra_channel_id"] == 999

        # Il canale community e' pubblico (si fa anche @everyone): niente
        # gergo da staff ("Controllo manuale/automatico") nel suo embed
        # dedicato, distinto dall'`info` del canale log.
        community_title = logger.calls[0]["community_title"]
        community_info = logger.calls[0]["community_info"]
        assert community_title and "calendario" in community_title.lower()
        assert "controllo" not in community_info.lower()
        assert SET_A_URL in community_info

        # Nome espansione (dallo slug URL) e periodo coperto (dal calendario
        # costruito) - il contenuto in piu' richiesto oltre al link nudo.
        assert community_title == "📅 Calendario Eventi Arena — Set A"
        expected_period = arena_event_schedule.format_period_covered(expected_months)
        assert expected_period in community_info
