"""
calendar_image.py

Draws, for a single month, the Arena event calendar image from the data
already structured by `features.monitors.event_schedule.build_month_calendar()`
({category: [(start_day, end_day, event_name), ...]}). Rendered text is in
Italian, since the image is posted to the community.

The image is an agenda: one row per event, grouped by Limited / Constructed /
Metagame / Eventi vari (grouping and merging live in `calendar_model`). Each
row has the exact dates and weekdays on the left, the full event name and its
Wizards categories in the middle, and a thin strip on the right that marks
the days of the month the event covers. The name is never squeezed into a bar
or moved around, so nothing gets truncated. The image is fixed-width and as
tall as it needs to be, so it reads well on a phone. Design and the layouts it
beat: docs/adr/0006-event-calendar-agenda-layout.md.
"""

import calendar as calendar_module
from datetime import date
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from core.console import log
from features.monitors.calendar_model import (
    GROUP_CONSTRUCTED,
    GROUP_LIMITED,
    GROUP_METAGAME,
    GROUP_OTHER,
    AgendaRow,
    build_agenda,
)
from features.monitors.event_schedule import MONTHS_IT

WEEKDAYS_IT = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


class EventCalendarImageGenerator:
    WIDTH = 900
    MARGIN = 32
    TITLE_TOP = 26
    CONTENT_TOP = 100
    BOTTOM_PADDING = 24

    DATE_COLUMN_WIDTH = 150
    NAME_MAX_LINES = 3
    NAME_LINE_HEIGHT = 26
    ROW_PADDING = 20
    CAPTION_LINE_HEIGHT = 20
    CAPTION_GAP = 2
    CAPTION_MAX_LINES = 4
    GROUP_HEADER_HEIGHT = 52

    # Strip of day ticks at the right of each row. Fixed tick width, so a
    # 28-day month is just shorter than a 31-day one.
    TICK_WIDTH = 6
    TICK_HEIGHT = 14

    TITLE_FONT_SIZE = 32
    GROUP_FONT_SIZE = 18
    DATES_FONT_SIZE = 21
    WEEKDAY_FONT_SIZE = 13
    NAME_FONT_SIZE = 20
    CAPTION_FONT_SIZE = 15

    # Neutral warm background: no blue. The group colors are dark enough for
    # the strip to stand out on it (contrast >= 4.5:1 against BG_COLOR).
    BG_COLOR = (247, 245, 240)
    TICK_BG_COLOR = (240, 237, 230)
    TICK_WEEKEND_COLOR = (236, 232, 224)
    SEPARATOR_COLOR = (218, 214, 205)
    TEXT_PRIMARY = (30, 30, 34)
    TEXT_SECONDARY = (105, 105, 114)

    GROUP_COLORS = {
        GROUP_LIMITED: (13, 124, 102),
        GROUP_CONSTRUCTED: (166, 94, 0),
        GROUP_METAGAME: (192, 57, 43),
        GROUP_OTHER: (112, 72, 176),
    }

    @classmethod
    def _try_font(cls, size, bold=False):
        names = [
            "arialbd.ttf" if bold else "arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        for name in names:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    @classmethod
    def _fit_text(cls, draw: ImageDraw.ImageDraw, text: str, font, max_width: float) -> str:
        """Truncates with an ellipsis if the text doesn't fit on one line."""
        if draw.textlength(text, font=font) <= max_width:
            return text
        truncated = text
        while truncated and draw.textlength(truncated + "…", font=font) > max_width:
            truncated = truncated[:-1]
        return f"{truncated.rstrip()}…"

    @classmethod
    def _wrap_text(
        cls, draw: ImageDraw.ImageDraw, text: str, font, max_width: float, max_lines: int
    ) -> list[str]:
        """Greedy word wrap. Past `max_lines` the last line ends with an
        ellipsis instead of growing the row without limit."""
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if not current or draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = cls._fit_text(draw, f"{lines[-1]} …", font, max_width)
        return lines

    @classmethod
    def _caption_lines(
        cls, draw: ImageDraw.ImageDraw, categories: tuple[str, ...], font, max_width: float
    ) -> list[str]:
        """Wraps the categories caption one category at a time, so a name like
        "Pick-Two Draft" is never split across two lines. A single category
        wider than the column is cut with an ellipsis."""
        lines: list[str] = []
        current = ""
        for category in categories:
            candidate = f"{current} · {category}" if current else category
            if not current or draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = category
        lines.append(current)
        lines = [cls._fit_text(draw, line, font, max_width) for line in lines]
        if len(lines) > cls.CAPTION_MAX_LINES:
            lines = lines[: cls.CAPTION_MAX_LINES]
            lines[-1] = cls._fit_text(draw, f"{lines[-1]} …", font, max_width)
        return lines

    @classmethod
    def _date_labels(cls, year: int, month: int, row: AgendaRow) -> tuple[str, str]:
        """("3 – 12", "mar → gio"), or ("21", "sab") for a one-day event."""
        first = WEEKDAYS_IT[date(year, month, row.start_day).weekday()]
        if row.start_day == row.end_day:
            return str(row.start_day), first
        last = WEEKDAYS_IT[date(year, month, row.end_day).weekday()]
        return f"{row.start_day} – {row.end_day}", f"{first} → {last}"

    @classmethod
    def create_month_calendar(
        cls,
        year: int,
        month: int,
        category_entries: dict[str, list[tuple[int, int, str]]],
    ) -> BytesIO:
        """Agenda image of one month: a section per group, one row per event."""

        agenda = build_agenda(category_entries)
        if agenda.unclassified:
            log(
                "[EVENT SCHEDULE] WARN events without a known format, shown under "
                f"'{GROUP_OTHER}': {', '.join(agenda.unclassified)} - a manual check is "
                "recommended (calendar_model keywords)"
            )

        last_day = calendar_module.monthrange(year, month)[1]
        font_title = cls._try_font(cls.TITLE_FONT_SIZE, bold=True)
        font_group = cls._try_font(cls.GROUP_FONT_SIZE, bold=True)
        font_dates = cls._try_font(cls.DATES_FONT_SIZE, bold=True)
        font_weekday = cls._try_font(cls.WEEKDAY_FONT_SIZE)
        font_name = cls._try_font(cls.NAME_FONT_SIZE, bold=True)
        font_caption = cls._try_font(cls.CAPTION_FONT_SIZE)

        strip_width = last_day * cls.TICK_WIDTH
        name_x = cls.MARGIN + cls.DATE_COLUMN_WIDTH
        name_width = cls.WIDTH - cls.MARGIN - strip_width - 24 - name_x
        strip_x = cls.WIDTH - cls.MARGIN - strip_width

        # Measure first, so the canvas height is known before drawing.
        measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        laid_out: list[tuple[str, list[tuple[AgendaRow, list[str], list[str], int]]]] = []
        total_height = cls.CONTENT_TOP + cls.BOTTOM_PADDING
        for group, rows in agenda.groups.items():
            total_height += cls.GROUP_HEADER_HEIGHT
            measured = []
            for row in rows:
                lines = cls._wrap_text(measure, row.name, font_name, name_width, cls.NAME_MAX_LINES)
                caption = cls._caption_lines(measure, row.categories, font_caption, name_width)
                height = (
                    len(lines) * cls.NAME_LINE_HEIGHT
                    + cls.ROW_PADDING
                    + cls.CAPTION_GAP
                    + len(caption) * cls.CAPTION_LINE_HEIGHT
                )
                measured.append((row, lines, caption, height))
                total_height += height
            laid_out.append((group, measured))

        canvas = Image.new("RGB", (cls.WIDTH, total_height), cls.BG_COLOR)
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (cls.MARGIN, cls.TITLE_TOP),
            f"{MONTHS_IT.get(month, month)} {year}",
            fill=cls.TEXT_PRIMARY,
            font=font_title,
        )

        y = cls.CONTENT_TOP
        for group, measured in laid_out:
            color = cls.GROUP_COLORS[group]
            draw.rounded_rectangle([cls.MARGIN, y + 18, cls.MARGIN + 18, y + 36], radius=5, fill=color)
            draw.text((cls.MARGIN + 30, y + 15), group, fill=cls.TEXT_PRIMARY, font=font_group)
            y += cls.GROUP_HEADER_HEIGHT

            for row, lines, caption, height in measured:
                draw.rounded_rectangle(
                    [cls.MARGIN - 12, y + 4, cls.MARGIN - 8, y + height - 4], radius=2, fill=color
                )
                dates, weekdays = cls._date_labels(year, month, row)
                draw.text((cls.MARGIN, y + 10), dates, fill=cls.TEXT_PRIMARY, font=font_dates)
                draw.text((cls.MARGIN, y + 40), weekdays, fill=cls.TEXT_SECONDARY, font=font_weekday)

                text_y = y + 10
                for line in lines:
                    draw.text((name_x, text_y), line, fill=cls.TEXT_PRIMARY, font=font_name)
                    text_y += cls.NAME_LINE_HEIGHT
                for caption_line in caption:
                    draw.text((name_x, text_y + 1), caption_line, fill=cls.TEXT_SECONDARY, font=font_caption)
                    text_y += cls.CAPTION_LINE_HEIGHT

                for day in range(1, last_day + 1):
                    x = strip_x + (day - 1) * cls.TICK_WIDTH
                    if row.start_day <= day <= row.end_day:
                        tick_color = color
                    elif date(year, month, day).weekday() >= 5:
                        tick_color = cls.TICK_WEEKEND_COLOR
                    else:
                        tick_color = cls.TICK_BG_COLOR
                    mid = y + height / 2
                    draw.rectangle(
                        [x, mid - cls.TICK_HEIGHT / 2, x + cls.TICK_WIDTH - 1, mid + cls.TICK_HEIGHT / 2],
                        fill=tick_color,
                    )

                draw.line(
                    [(cls.MARGIN, y + height), (cls.WIDTH - cls.MARGIN, y + height)],
                    fill=cls.SEPARATOR_COLOR,
                )
                y += height

        output = BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        output.seek(0)
        return output
