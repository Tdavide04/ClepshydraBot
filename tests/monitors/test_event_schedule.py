import asyncio
import json
from datetime import date

import pytest

import features.monitors.event_schedule as event_schedule


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Every test starts from a clean state on disk and in cache, like
    isolated_overrides in test_arena_overrides.py."""
    monkeypatch.setattr(event_schedule, "STATE_PATH", str(tmp_path / "arena_event_schedule_state.json"))
    monkeypatch.setattr(event_schedule, "_state_cache", None)
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

    monkeypatch.setattr(event_schedule, "_fetch_sitemap_event_schedule_urls", fake_sitemap)
    monkeypatch.setattr(event_schedule, "_fetch_page_html", fake_page)


SET_A_URL = "https://magic.wizards.com/en/news/mtg-arena/set-a-event-schedule"
SET_B_URL = "https://magic.wizards.com/en/news/mtg-arena/set-b-event-schedule"

# Realistic fragment of the "Full Event Calendar" section seen on the real
# pages (the-hobbit-event-schedule, teenage-mutant-ninja-turtles-event-schedule):
# a bare heading (no CSS attribute, unlike the side navigation cards)
# immediately followed by a <ul><li>.
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
<ul><li>Must be ignored: it sits outside &lt;/article&gt;</li></ul>
</aside>
</body></html>
"""

NO_CALENDAR_HTML = "<html><body><article><h2>Some Other Page</h2><p>nothing here</p></article></body></html>"

# Regression 2026-09-21: reality-fracture-event-schedule started publishing
# the "Full Event Calendar" heading WITH attributes
# (id="FRACalendar" style="scroll-margin-top: 70px;"), unlike the bare <h2>
# of every page seen so far - it triggered an
# ARENA_EVENT_SCHEDULE_UNPARSEABLE WARN in production, a false positive
# (minimal drift, not a section that was really missing).
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

# Realistic fragment of the real sitemap (magic.wizards.com/en/sitemap.xml):
# a mix of event-schedule pages, weekly announcements posts (to exclude) and
# completely unrelated product pages (to exclude).
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
        found = event_schedule._parse_sitemap_xml(SAMPLE_SITEMAP_XML)

        assert found == {
            "https://magic.wizards.com/en/news/mtg-arena/the-hobbit-event-schedule": "2026-09-02T16:05:08.364Z",
            "https://magic.wizards.com/en/news/mtg-arena/teenage-mutant-ninja-turtles-event-schedule": "2026-03-02T18:00:08.627Z",
        }

    def test_ignores_weekly_announcements_and_unrelated_pages(self):
        found = event_schedule._parse_sitemap_xml(SAMPLE_SITEMAP_XML)

        urls = set(found.keys())
        assert not any("announcements-" in u for u in urls)
        assert not any("/products/" in u for u in urls)

    def test_malformed_xml_returns_empty_dict_instead_of_raising(self):
        assert event_schedule._parse_sitemap_xml("<not valid xml") == {}


class TestParseFullEventCalendar:
    def test_extracts_categories_and_entries(self):
        categories = event_schedule.parse_full_event_calendar(VALID_CALENDAR_HTML)

        assert categories is not None
        assert categories["Premier Draft"] == ["August 11–September 29: Magic: The Gathering | Set A"]
        assert categories["Quick Draft"] == [
            "August 11–19: Duskmourn: House of Horror",
            "August 20–30: Set A",
        ]

    def test_ignores_content_outside_article_boundary(self):
        categories = event_schedule.parse_full_event_calendar(VALID_CALENDAR_HTML)

        assert "Not part of the calendar" not in categories

    def test_returns_none_when_calendar_heading_missing(self):
        assert event_schedule.parse_full_event_calendar(NO_CALENDAR_HTML) is None

    def test_recognizes_the_calendar_heading_even_with_attributes(self):
        """Regression: the 'Full Event Calendar' heading can carry attributes
        (id/style) as on reality-fracture-event-schedule, not just the bare
        <h2> of earlier pages."""
        categories = event_schedule.parse_full_event_calendar(ATTRIBUTED_CALENDAR_HEADING_HTML)

        assert categories is not None
        assert categories["Premier Draft"] == ["September 29–November 9: Reality Fracture"]


class TestParseEventEntry:
    def test_parses_range_spanning_two_months(self):
        parsed = event_schedule.parse_event_entry("August 11–September 29: Magic: The Gathering | The Hobbit")
        assert parsed == {
            "start_month": 8,
            "start_day": 11,
            "end_month": 9,
            "end_day": 29,
            "name": "Magic: The Gathering | The Hobbit",
        }

    def test_parses_range_within_a_single_month_without_repeating_month_name(self):
        parsed = event_schedule.parse_event_entry("August 11–19: Duskmourn: House of Horror")
        assert parsed["start_month"] == 8
        assert parsed["end_month"] == 8
        assert parsed["start_day"] == 11
        assert parsed["end_day"] == 19
        # The name can contain other ':' besides the one separating the date
        assert parsed["name"] == "Duskmourn: House of Horror"

    def test_accepts_plain_hyphen_as_well_as_en_dash(self):
        parsed = event_schedule.parse_event_entry("August 11-19: Set")
        assert parsed is not None

    def test_returns_none_for_text_without_a_recognizable_date(self):
        assert event_schedule.parse_event_entry("Event without a date") is None


class TestBuildMonthCalendar:
    def test_splits_a_multi_month_range_at_month_boundaries(self):
        categories = {
            "Premier Draft": ["August 11–September 29: The Hobbit"],
        }
        result = event_schedule.build_month_calendar(categories, reference_date=date(2026, 9, 15))

        assert result[(2026, 8)]["Premier Draft"] == [(11, 31, "The Hobbit")]
        assert result[(2026, 9)]["Premier Draft"] == [(1, 29, "The Hobbit")]

    def test_single_month_range_is_not_split(self):
        categories = {"Quick Draft": ["August 11–19: Duskmourn"]}
        result = event_schedule.build_month_calendar(categories, reference_date=date(2026, 9, 15))

        assert list(result.keys()) == [(2026, 8)]
        assert result[(2026, 8)]["Quick Draft"] == [(11, 19, "Duskmourn")]

    def test_unparseable_entry_is_silently_excluded(self):
        categories = {"Quick Draft": ["Event without a date", "August 11–19: Duskmourn"]}
        result = event_schedule.build_month_calendar(categories, reference_date=date(2026, 9, 15))

        assert result[(2026, 8)]["Quick Draft"] == [(11, 19, "Duskmourn")]

    def test_range_crossing_december_into_january_bumps_the_year(self):
        categories = {"Quick Draft": ["December 28–January 4: New Year Set"]}
        result = event_schedule.build_month_calendar(categories, reference_date=date(2026, 12, 1))

        assert result[(2026, 12)]["Quick Draft"] == [(28, 31, "New Year Set")]
        assert result[(2027, 1)]["Quick Draft"] == [(1, 4, "New Year Set")]

    def test_entry_referencing_january_while_checking_in_december_is_next_year(self):
        """An entry (e.g. Flashback) falling in January while the check runs
        in December belongs to next year, not to one 11 months in the past -
        covers the _infer_start_year heuristic."""
        categories = {"Quick Draft": ["January 5–11: Some Set"]}
        result = event_schedule.build_month_calendar(categories, reference_date=date(2026, 12, 20))

        assert list(result.keys()) == [(2027, 1)]

    def test_recent_past_month_stays_in_the_current_year(self):
        """A Flashback entry referring to a recent month (not eleven months
        back) must stay in the current year, not be wrongly pushed to next
        year."""
        categories = {"Flashback Premier Draft": ["August 25–September 7: LOTR"]}
        result = event_schedule.build_month_calendar(categories, reference_date=date(2026, 9, 15))

        assert (2026, 8) in result
        assert (2027, 8) not in result

    def test_no_parseable_entries_returns_empty_dict(self):
        categories = {"Quick Draft": ["Event without a date"]}
        result = event_schedule.build_month_calendar(categories, reference_date=date(2026, 9, 15))
        assert result == {}


class TestExtractSetNameFromUrl:
    def test_strips_the_event_schedule_suffix_and_title_cases_words(self):
        url = "https://magic.wizards.com/en/news/mtg-arena/the-hobbit-event-schedule"
        assert event_schedule.extract_set_name_from_url(url) == "The Hobbit"

    def test_handles_a_trailing_slash(self):
        url = "https://magic.wizards.com/en/news/mtg-arena/duskmourn-event-schedule/"
        assert event_schedule.extract_set_name_from_url(url) == "Duskmourn"


class TestFormatPeriodCovered:
    def test_returns_none_for_an_empty_calendar(self):
        assert event_schedule.format_period_covered({}) is None

    def test_single_month_range_has_no_repeated_year(self):
        categories = {"Quick Draft": ["August 11-19: Duskmourn"]}
        month_calendar = event_schedule.build_month_calendar(categories, reference_date=date(2026, 9, 15))
        assert event_schedule.format_period_covered(month_calendar) == "11 Agosto - 19 Agosto 2026"

    def test_multi_month_range_spans_both_months(self):
        categories = {"Premier Draft": ["August 11-September 29: The Hobbit"]}
        month_calendar = event_schedule.build_month_calendar(categories, reference_date=date(2026, 9, 15))
        assert event_schedule.format_period_covered(month_calendar) == "11 Agosto - 29 Settembre 2026"

    def test_range_crossing_into_next_year_shows_both_years(self):
        categories = {"Quick Draft": ["December 28-January 4: New Year Set"]}
        month_calendar = event_schedule.build_month_calendar(categories, reference_date=date(2026, 12, 1))
        assert event_schedule.format_period_covered(month_calendar) == "28 Dicembre 2026 - 4 Gennaio 2027"

    def test_covers_the_full_span_across_multiple_categories(self):
        """The period must reflect the widest range across ALL categories,
        not only the first one found."""
        categories = {
            "Quick Draft": ["September 1-7: Secrets of Strixhaven"],
            "Premier Draft": ["August 11-19: Duskmourn"],
        }
        month_calendar = event_schedule.build_month_calendar(categories, reference_date=date(2026, 9, 15))
        assert event_schedule.format_period_covered(month_calendar) == "11 Agosto - 7 Settembre 2026"


class TestPickLatest:
    def test_returns_the_entry_with_the_most_recent_lastmod(self):
        entries = {SET_A_URL: "2026-08-03T00:00:00Z", SET_B_URL: "2026-06-15T00:00:00Z"}
        assert event_schedule._pick_latest(entries) == (SET_A_URL, "2026-08-03T00:00:00Z")

    def test_returns_none_for_empty_input(self):
        assert event_schedule._pick_latest({}) is None


class TestCheckEventScheduleUpdates:
    def test_first_check_reports_only_the_latest_page_not_older_ones(self, monkeypatch):
        """Direct regression for the flood reported in production: on the
        first run on a new machine (empty state), the sitemap held 4 Event
        Schedule pages still online (Wizards doesn't remove past sets' pages)
        and all 4 were notified at once. Only one must come through: the
        currently active set's (newest lastmod)."""
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={
                SET_A_URL: "2026-08-03T00:00:00Z",  # active set
                SET_B_URL: "2026-06-15T00:00:00Z",  # ended set, still in the sitemap
            },
            pages={SET_A_URL: VALID_CALENDAR_HTML, SET_B_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )

        results = run(event_schedule.check_event_schedule_updates())

        assert [r["url"] for r in results] == [SET_A_URL]
        assert SET_B_URL not in calls, "the ended set's page must not even be downloaded"

    def test_second_check_skips_when_latest_is_unchanged(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03T00:00:00Z"},
            pages={SET_A_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        run(event_schedule.check_event_schedule_updates())

        calls.clear()
        results = run(event_schedule.check_event_schedule_updates())

        assert results == [], "lastmod unchanged: the page must not be fetched again"
        assert SET_A_URL not in calls
        assert "sitemap" in calls, "the sitemap must still be re-checked to know whether something changed"

    def test_changed_lastmod_on_the_latest_page_triggers_reprocessing(self, monkeypatch):
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03T00:00:00Z"},
            pages={SET_A_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        run(event_schedule.check_event_schedule_updates())

        # Simulates the in-place update seen on the-hobbit-event-schedule
        # (published August 3, lastmod updated to September 2).
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-09-02T00:00:00Z"},
            pages={SET_A_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        calls.clear()
        results = run(event_schedule.check_event_schedule_updates())

        assert [r["url"] for r in results] == [SET_A_URL]
        assert SET_A_URL in calls

        with open(event_schedule.STATE_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["latest_lastmod"] == "2026-09-02T00:00:00Z"

    def test_a_newer_page_overtakes_the_previous_latest(self, monkeypatch):
        """If a new set comes out with a newer lastmod than the one known so
        far, it must become the 'latest' - even if the old page's lastmod
        didn't change."""
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03T00:00:00Z"},
            pages={SET_A_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        run(event_schedule.check_event_schedule_updates())

        _install_fake_network(
            monkeypatch,
            sitemap={
                SET_A_URL: "2026-08-03T00:00:00Z",  # unchanged
                SET_B_URL: "2026-09-05T00:00:00Z",  # new set, more recent
            },
            pages={SET_A_URL: VALID_CALENDAR_HTML, SET_B_URL: VALID_CALENDAR_HTML},
            calls=calls,
        )
        calls.clear()
        results = run(event_schedule.check_event_schedule_updates())

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
        run(event_schedule.check_event_schedule_updates())

        calls.clear()
        results = run(event_schedule.check_event_schedule_updates(force=True))

        assert [r["url"] for r in results] == [SET_A_URL]
        assert SET_A_URL in calls

    def test_unparseable_page_is_reported_not_dropped(self, monkeypatch):
        """If the 'Full Event Calendar' section isn't found, the result must
        still show up with categories=None (so the caller can report it), not
        be silently dropped."""
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03T00:00:00Z"},
            pages={SET_A_URL: NO_CALENDAR_HTML},
            calls=calls,
        )

        results = run(event_schedule.check_event_schedule_updates())

        assert len(results) == 1
        assert results[0]["categories"] is None
        # Even if unparseable, the state must still be updated so the same
        # unchanged page isn't retried on every run.
        with open(event_schedule.STATE_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["latest_url"] == SET_A_URL

    def test_failed_fetch_does_not_update_state(self, monkeypatch):
        """If the page fetch fails (returns None), the page must not be marked
        as seen: it must be retried on the next run."""
        calls = []
        _install_fake_network(
            monkeypatch,
            sitemap={SET_A_URL: "2026-08-03T00:00:00Z"},
            pages={},  # no response -> _fetch_page_html returns None
            calls=calls,
        )

        results = run(event_schedule.check_event_schedule_updates())

        assert results == []
        import os

        assert not os.path.exists(event_schedule.STATE_PATH)


class FakeLogger:
    def __init__(self):
        self.calls = []

    async def send_log(
        self,
        level,
        event,
        user=None,
        channel=None,
        info=None,
        fields=None,
        files=None,
        extra_channel_id=None,
        community_title=None,
        community_info=None,
    ):
        self.calls.append(
            {
                "level": level,
                "event": event,
                "info": info,
                "fields": fields or [],
                "files": files or [],
                "extra_channel_id": extra_channel_id,
                "community_title": community_title,
                "community_info": community_info,
            }
        )


class TestSendEventScheduleLog:
    def test_unparseable_page_sends_a_single_warn_with_no_files(self):
        logger = FakeLogger()
        result = {"url": SET_A_URL, "lastmod": "2026-08-03T00:00:00Z", "categories": None}

        run(event_schedule.send_event_schedule_log(logger, result, user=None, forced=False))

        assert len(logger.calls) == 1
        assert logger.calls[0]["level"] == "WARN"
        assert logger.calls[0]["event"] == "ARENA_EVENT_SCHEDULE_UNPARSEABLE"
        assert logger.calls[0]["files"] == []
        assert logger.calls[0]["extra_channel_id"] is None, (
            "a failed parse is staff noise, not community content"
        )

    def test_categories_without_parseable_dates_send_a_warn_with_no_files(self):
        """The categories were parsed (categories isn't None) but no entry
        follows the expected date format: build_month_calendar() returns
        empty, and there is nothing to draw - a distinct WARN must arrive
        instead of an empty image or an error."""
        logger = FakeLogger()
        categories = {"Premier Draft": ["Event without a recognizable date"]}
        result = {"url": SET_A_URL, "lastmod": "x", "categories": categories}

        run(event_schedule.send_event_schedule_log(logger, result, user=None, forced=False))

        assert len(logger.calls) == 1
        assert logger.calls[0]["level"] == "WARN"
        assert logger.calls[0]["event"] == "ARENA_EVENT_SCHEDULE_NO_DATES"
        assert logger.calls[0]["files"] == []
        assert logger.calls[0]["extra_channel_id"] is None, (
            "no recognized date is staff noise, not community content"
        )

    def test_valid_categories_attach_one_image_per_month_and_post_to_the_community_channel(self, monkeypatch):
        """Replaces the old text-embed-field design: one calendar image per
        month involved, attached to the same INFO message, instead of
        describing events in words. A real update also goes to the community
        channel (extra_channel_id), unlike the two WARNs above."""
        import config.config as config_module

        monkeypatch.setattr(config_module, "COMUNICATION_CHANNEL_ID", 999)

        logger = FakeLogger()
        categories = {
            "Premier Draft": ["August 11-19: Duskmourn: House of Horror"],
            "Quick Draft": ["September 1-7: Secrets of Strixhaven"],
        }
        result = {"url": SET_A_URL, "lastmod": "x", "categories": categories}

        run(event_schedule.send_event_schedule_log(logger, result, user=None, forced=False))

        # Same default (no explicit reference_date) as the code under test,
        # so the expectation doesn't depend on the real date the test runs on.
        expected_months = event_schedule.build_month_calendar(categories)

        assert len(logger.calls) == 1
        assert logger.calls[0]["level"] == "INFO"
        assert logger.calls[0]["event"] == "ARENA_EVENT_SCHEDULE_UPDATED"
        assert len(logger.calls[0]["files"]) == len(expected_months)
        assert all(f.filename.startswith("calendario_") for f in logger.calls[0]["files"])
        assert logger.calls[0]["extra_channel_id"] == 999

        # The community channel is public (@everyone gets pinged): no staff
        # jargon ("Forced manual check"/"Automatic check") in its dedicated
        # embed, distinct from the log channel's `info`.
        community_title = logger.calls[0]["community_title"]
        community_info = logger.calls[0]["community_info"]
        assert community_title and "calendario" in community_title.lower()
        assert "check" not in community_info.lower()
        assert SET_A_URL in community_info

        # Expansion name (from the URL slug) and period covered (from the
        # built calendar) - the extra content asked for beyond the bare link.
        assert community_title == "📅 Calendario Eventi Arena — Set A"
        expected_period = event_schedule.format_period_covered(expected_months)
        assert expected_period in community_info
