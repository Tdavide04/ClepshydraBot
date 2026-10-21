from io import BytesIO

from PIL import Image

from features.monitors.calendar_image import EventCalendarImageGenerator

SAMPLE_ENTRIES = {
    "Premier Draft": [(10, 30, "Star Trek")],
    "Pick-Two Draft": [(10, 30, "Star Trek")],
    "Quick Draft": [(7, 18, "Bloomburrow"), (19, 28, "Star Trek")],
    "Arena Direct": [(13, 22, "Arena Direct for Star Trek Collector Booster boxes")],
    "Midweek Magic": [(24, 25, "Artisan Brawl")],
}


def _render(year=2026, month=11, entries=SAMPLE_ENTRIES) -> Image.Image:
    buffer = EventCalendarImageGenerator.create_month_calendar(year, month, entries)
    assert isinstance(buffer, BytesIO)
    return Image.open(buffer)


class TestCreateMonthCalendar:
    def test_returns_a_png(self):
        image = _render()

        assert image.format == "PNG"

    def test_has_a_fixed_phone_friendly_width(self):
        assert _render().width == 900
        assert _render(2027, 2, {"Quick Draft": [(1, 10, "Edge of Eternities")]}).width == 900

    def test_grows_taller_with_more_events(self):
        few = _render(entries={"Quick Draft": [(1, 5, "Bloomburrow")]})
        many = _render()

        assert many.height > few.height

    def test_a_very_long_name_does_not_make_the_image_wider(self):
        name = "Arena Direct: " + "Arena Powered Cube Draft for Star Trek Play Booster boxes " * 3
        image = _render(entries={"Arena Direct": [(25, 27, name)]})

        assert image.width == 900

    def test_a_row_with_many_categories_grows_to_show_them_all(self):
        """Regression: the categories caption was one line cut with "…", so the
        last categories of an event listed under many of them were lost."""
        one = _render(entries={"Premier Draft": [(1, 30, "Star Trek")]})
        many = _render(
            entries={
                category: [(1, 30, "Star Trek")]
                for category in (
                    "Premier Draft",
                    "Contender Draft",
                    "Pick-Two Draft",
                    "Traditional Draft",
                    "Flashback Premier Draft",
                    "Sealed and Traditional Sealed",
                )
            }
        )

        assert many.height > one.height

    def test_logs_a_warning_for_an_unclassified_event(self, capsys):
        _render(entries={"Midweek Magic": [(15, 16, "Momir")]})

        out = capsys.readouterr().out
        assert "WARN" in out
        assert "Momir" in out

    def test_stays_silent_when_every_event_is_classified(self, capsys):
        _render()

        assert capsys.readouterr().out == ""
