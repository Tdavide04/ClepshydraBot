"""
event_calendar_image_generator.py

Draws, for a single month, the Arena event calendar image from the data
already structured by `utils.arena_event_schedule.build_month_calendar()`
({category: [(start_day, end_day, event_name), ...]}). Rendered text is in
Italian, since the image is posted to the community.

`create_month_calendar()` (used in production) is a Gantt with one row per
SINGLE CATEGORY (as the Wizards pages list them, 13-15 rows - not merged by
family), colored by family and with cleaned names in the bars, followed by a
detailed text list below, grouped by family, with each event's full name and
the original category in parentheses. It is the result of three rounds of
iteration with mock-ups on real data (see also
docs/adr/0001-event-calendar-image-layout.md):
- a classic calendar grid (one text block per active category in every day
  cell) is unreadable because 4-6 categories stay active for weeks and
  repeat identically in every cell, pushing out of view (behind a "+N more")
  the events that change day by day;
- an attempt with an "always-on" band + a grid for the rest was better, but
  text stayed truncated in the narrow cells (~160px) for long names;
- a swimlane with one row per FAMILY (6 rows, no text in the bars, details
  in a list below) solved the truncation but lost per-category granularity
  (e.g. it was no longer obvious at a glance that "Pick-Two Draft" and
  "Traditional Draft" are really two distinct queues, not the same thing
  drawn twice) - the final design brings back one row per category in the
  Gantt (as in the first attempt, create_month_panel) but keeps the later
  lessons: family colors instead of cyclic ones, cleaned names
  (_clean_name) instead of raw ones, and the detailed list below (inspired
  by arpgseasons.com/en/calendar, a season calendar for competing ARPG games
  with the same overlapping-time-series problem) for the cases where text
  doesn't fit in the bar even with cleaned names;
- colors are grouped by family (not one color per category) because with
  13-15 categories a 1:1 palette gives no pattern recognizable at a glance;
  the family classification is a keyword heuristic on the category name
  (_classify_family), not data coming from the Wizards page. Colors chosen
  by hand on explicit request (not cyclic).

`create_month_panel()` (the original design, cyclic palette per category and
raw names) stays in the module as is - no command calls it anymore, but
there is no reason to throw away working code in case a comparison is
needed again.
"""

import calendar as calendar_module
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from utils.arena_event_schedule import MONTHS_IT


class EventCalendarImageGenerator:

    PADDING_X = 40
    PADDING_TOP = 74
    PADDING_BOTTOM = 24

    ROW_LABEL_WIDTH = 190
    DAY_COL_WIDTH = 32
    # Height of a single "lane" within a category row. A category whose
    # events overlap in time (e.g. "Other Events", which on the real page
    # hosts several parallel exhibitions in the same period) takes several
    # lanes stacked vertically instead of squeezing the bars on top of each
    # other - without this, texts and labels of different events overlap in
    # the same space, unreadable.
    LANE_HEIGHT = 38
    BAR_HEIGHT = 26

    HEADER_HEIGHT = 26

    BG_COLOR = (18, 20, 30)
    GRID_COLOR = (50, 54, 68)
    GRID_COLOR_STRONG = (75, 80, 98)
    TEXT_PRIMARY = (230, 230, 235)
    TEXT_SECONDARY = (160, 160, 175)
    BAR_TEXT_COLOR = (18, 18, 22)
    ROW_LABEL_BG = (26, 28, 40)

    TITLE_FONT_SIZE = 26
    DAY_FONT_SIZE = 12
    ROW_LABEL_FONT_SIZE = 14
    BAR_FONT_SIZE = 12

    # Cyclic palette per category - assigned by index, not by name hash, so
    # the order (stable: it comes from a Python dict) stays consistent from
    # one render to the next for the same set of categories.
    CATEGORY_COLORS = [
        (99, 179, 237),
        (246, 173, 85),
        (154, 230, 180),
        (245, 101, 101),
        (183, 148, 244),
        (250, 240, 137),
        (129, 230, 217),
        (252, 129, 192),
    ]

    # ── Detailed list constants (below the Gantt) ──
    DETAIL_LINE_HEIGHT = 20
    DETAIL_HEADING_HEIGHT = 24
    DETAIL_GROUP_GAP = 10
    DETAIL_HEADING_FONT_SIZE = 13
    DETAIL_ITEM_FONT_SIZE = 12
    DETAIL_ITEM_COLOR = (170, 172, 185)
    DETAIL_CATEGORY_MAX_CHARS = 40

    # Color grouping by family (not per category): with 13-15 categories a
    # 1:1 palette gives no pattern recognizable at a glance. Keyword
    # heuristic on the name, not data coming from the Wizards page - see
    # _classify_family(). Colors chosen by hand (not cyclic) on explicit
    # request.
    FAMILY_COLORS = {
        "Premier Draft": (66, 133, 220),
        "Quick Draft": (67, 176, 108),
        "Flashback": (149, 105, 210),
        "Sealed & Cube": (108, 201, 230),
        "Metagame": (226, 140, 57),
        "Community": (222, 68, 68),
    }

    # Fixed order for band rows and legend, so it doesn't depend on the order
    # (non-deterministic for our purposes) in which categories appear on the
    # Wizards page.
    FAMILY_ORDER = [
        "Premier Draft", "Quick Draft", "Flashback",
        "Sealed & Cube", "Metagame", "Community",
    ]

    # Prefixes to strip from the event name shown in bars/pills: the
    # category (color) already says "what kind of event it is", so repeating
    # "Magic: The Gathering" or "Arena Direct for" in the text is pure noise
    # - see _clean_name().
    _ARENA_DIRECT_PREFIX = "arena direct for "
    _MTG_PREFIX = "magic: the gathering | "

    # Used in the detailed list when several months share the same list
    # (create_multi_month_calendar) - without the month, August "11-19" and
    # September "11-19" would be indistinguishable once merged into the same
    # family section.
    MONTH_ABBR_IT = {
        1: "gen", 2: "feb", 3: "mar", 4: "apr", 5: "mag", 6: "giu",
        7: "lug", 8: "ago", 9: "set", 10: "ott", 11: "nov", 12: "dic",
    }

    @classmethod
    def _try_font(cls, size, bold=False):
        names = [
            "arialbd.ttf" if bold else "arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        for name in names:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    @classmethod
    def create_month_panel(
        cls,
        year: int,
        month: int,
        last_day: int,
        category_entries: dict[str, list[tuple[int, int, str]]],
    ) -> BytesIO:
        """Draws a month's Gantt panel. `category_entries` is already clipped
        to the month's bounds by build_month_calendar() - this function only
        places bars/text, with no date logic."""

        categories = list(category_entries.keys())

        # Pre-pass: for each category, compute which lane each event goes on
        # (greedy interval scheduling) and how many lanes are needed in total
        # - this sets the row height BEFORE drawing.
        lanes_by_category: dict[str, list[int]] = {}
        lane_count_by_category: dict[str, int] = {}
        for category, entries in category_entries.items():
            assignment, n_lanes = cls._assign_lanes(entries)
            lanes_by_category[category] = assignment
            lane_count_by_category[category] = n_lanes

        row_heights = [lane_count_by_category[c] * cls.LANE_HEIGHT for c in categories]

        chart_width = last_day * cls.DAY_COL_WIDTH
        canvas_width = cls.PADDING_X + cls.ROW_LABEL_WIDTH + chart_width + cls.PADDING_X
        chart_height = sum(row_heights)
        canvas_height = cls.PADDING_TOP + cls.HEADER_HEIGHT + chart_height + cls.PADDING_BOTTOM

        canvas = Image.new("RGB", (canvas_width, canvas_height), cls.BG_COLOR)
        draw = ImageDraw.Draw(canvas)

        font_title = cls._try_font(cls.TITLE_FONT_SIZE, bold=True)
        font_day = cls._try_font(cls.DAY_FONT_SIZE)
        font_label = cls._try_font(cls.ROW_LABEL_FONT_SIZE, bold=True)
        font_bar = cls._try_font(cls.BAR_FONT_SIZE)

        # ── Title ───────────────────────────────────────────────
        title = f"{MONTHS_IT.get(month, month)} {year}"
        draw.text((cls.PADDING_X, 20), title, fill=cls.TEXT_PRIMARY, font=font_title)

        chart_x = cls.PADDING_X + cls.ROW_LABEL_WIDTH
        chart_y = cls.PADDING_TOP + cls.HEADER_HEIGHT

        # ── Day header ──────────────────────────────────────────
        for day in range(1, last_day + 1):
            x = chart_x + (day - 1) * cls.DAY_COL_WIDTH
            draw.text(
                (x + cls.DAY_COL_WIDTH / 2, cls.PADDING_TOP + cls.HEADER_HEIGHT / 2),
                str(day),
                fill=cls.TEXT_SECONDARY,
                font=font_day,
                anchor="mm",
            )
            is_week_boundary = day % 7 == 1
            line_color = cls.GRID_COLOR_STRONG if is_week_boundary else cls.GRID_COLOR
            draw.line(
                [(x, chart_y), (x, chart_y + chart_height)],
                fill=line_color,
                width=1,
            )
        draw.line(
            [(chart_x + chart_width, chart_y), (chart_x + chart_width, chart_y + chart_height)],
            fill=cls.GRID_COLOR_STRONG,
            width=1,
        )

        # ── Category rows + bars ────────────────────────────────
        row_y = chart_y
        for row_idx, category in enumerate(categories):
            row_height = row_heights[row_idx]
            color = cls.CATEGORY_COLORS[row_idx % len(cls.CATEGORY_COLORS)]
            lane_assignment = lanes_by_category[category]

            draw.rectangle(
                [cls.PADDING_X, row_y, chart_x, row_y + row_height],
                fill=cls.ROW_LABEL_BG,
            )
            draw.text(
                (cls.PADDING_X + 10, row_y + row_height / 2),
                category,
                fill=cls.TEXT_PRIMARY,
                font=font_label,
                anchor="lm",
            )
            draw.line(
                [(cls.PADDING_X, row_y + row_height), (chart_x + chart_width, row_y + row_height)],
                fill=cls.GRID_COLOR,
                width=1,
            )

            for entry_idx, (day_start, day_end, name) in enumerate(category_entries[category]):
                lane_y = row_y + lane_assignment[entry_idx] * cls.LANE_HEIGHT
                bar_x1 = chart_x + (day_start - 1) * cls.DAY_COL_WIDTH
                bar_x2 = chart_x + day_end * cls.DAY_COL_WIDTH
                bar_y1 = lane_y + (cls.LANE_HEIGHT - cls.BAR_HEIGHT) / 2
                bar_y2 = bar_y1 + cls.BAR_HEIGHT

                draw.rounded_rectangle(
                    [bar_x1 + 2, bar_y1, bar_x2 - 2, bar_y2],
                    radius=5,
                    fill=color,
                )

                bar_width = bar_x2 - bar_x1 - 4
                label = cls._fit_text(draw, name, font_bar, bar_width - 10)
                if label:
                    draw.text(
                        ((bar_x1 + bar_x2) / 2, (bar_y1 + bar_y2) / 2),
                        label,
                        fill=cls.BAR_TEXT_COLOR,
                        font=font_bar,
                        anchor="mm",
                    )

            row_y += row_height

        output = BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        output.seek(0)
        return output

    # Vertical space between one month panel and the next when several
    # months are composed into a single image (create_multi_month_calendar).
    MULTI_MONTH_GAP = 40

    @classmethod
    def create_multi_month_calendar(
        cls,
        months: list[tuple[int, int, dict[str, list[tuple[int, int, str]]]]],
    ) -> BytesIO:
        """Composes into a single image one Gantt per month, followed by ONE
        detailed list merging every month's entries (grouped by family, with
        the month shown on each line to tell "11-19 ago" from "11-19 set") -
        instead of repeating a structurally identical list under each
        panel."""

        gantt_imgs = []
        combined_family_detail: dict[str, list[tuple[int, int, int, str, str]]] = {}

        for year, month, category_entries in months:
            cleaned_entries = cls._clean_category_entries(category_entries)
            gantt_imgs.append(cls._render_gantt_panel(year, month, cleaned_entries))

            month_detail = cls._build_family_detail(month, cleaned_entries)
            for family, entries in month_detail.items():
                combined_family_detail.setdefault(family, []).extend(entries)

        gantt_stack = cls._stack_vertically(gantt_imgs, gap=cls.MULTI_MONTH_GAP)
        detail_img = cls._render_detail_section(
            combined_family_detail, width=gantt_stack.width, show_month=True
        )
        canvas = cls._stack_vertically([gantt_stack, detail_img], gap=30)

        output = BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        output.seek(0)
        return output

    @classmethod
    def _assign_lanes(cls, entries: list[tuple[int, int, str]]) -> tuple[list[int], int]:
        """Greedy interval scheduling: assigns each event (by original index,
        not reordered) the first free lane - a lane is free if its last
        placed event ends before this one starts. Returns (lane_per_index,
        total_lane_count)."""

        order = sorted(range(len(entries)), key=lambda i: entries[i][0])
        lane_last_end: list[int] = []
        assignment = [0] * len(entries)

        for idx in order:
            day_start, day_end, _name = entries[idx]
            placed_lane = None
            for lane_idx, last_end in enumerate(lane_last_end):
                if last_end < day_start:
                    placed_lane = lane_idx
                    break
            if placed_lane is None:
                placed_lane = len(lane_last_end)
                lane_last_end.append(day_end)
            else:
                lane_last_end[placed_lane] = day_end
            assignment[idx] = placed_lane

        return assignment, max(1, len(lane_last_end))

    @classmethod
    def _fit_text(cls, draw: ImageDraw.ImageDraw, text: str, font, max_width: float) -> str:
        """Truncates with an ellipsis if the event name doesn't fit in the bar."""
        if max_width <= 0:
            return ""
        if draw.textlength(text, font=font) <= max_width:
            return text
        truncated = text
        while truncated and draw.textlength(truncated + "…", font=font) > max_width:
            truncated = truncated[:-1]
        return f"{truncated}…" if truncated else ""

    # ==========================================
    # WEEKLY GRID + "ALWAYS-ON" BAND
    # ==========================================

    @classmethod
    def _classify_family(cls, category: str) -> str:
        """Keyword heuristic on the category name - not data coming from the
        Wizards page. The order of the checks matters:
        - "Flashback Premier Draft" contains both "flashback" and "draft":
          Flashback must be checked first, otherwise it would land in Draft.
        - "September Format: ... Sealed" contains both "format" and
          "sealed": it is a timed/metagame event (like Arena Direct), not a
          real Sealed, so Metagame must be checked before Sealed & Cube.
        - "Quick Draft" contains "draft": it must be checked before the
          generic "draft" catch-all (Premier/Pick-Two/Traditional/Contender
          Draft)."""

        lowered = category.lower()
        if "flashback" in lowered:
            return "Flashback"
        if "metagame" in lowered or "arena direct" in lowered or "format:" in lowered:
            return "Metagame"
        if "cube" in lowered or "sealed" in lowered:
            return "Sealed & Cube"
        if "quick draft" in lowered:
            return "Quick Draft"
        if "draft" in lowered:
            return "Premier Draft"
        return "Community"

    @classmethod
    def _clean_name(cls, name: str) -> str:
        """Strips the "Arena Direct for " and "Magic: The Gathering | "
        prefixes from the event name - the color (family) already conveys the
        type, so repeating it in the text (e.g. "Arena Direct for Magic: The
        Gathering | The Hobbit") was just noise compared with showing only the
        expansion ("The Hobbit")."""

        text = name.strip()
        if text.lower().startswith(cls._ARENA_DIRECT_PREFIX):
            text = text[len(cls._ARENA_DIRECT_PREFIX):]
        if text.lower().startswith(cls._MTG_PREFIX):
            text = text[len(cls._MTG_PREFIX):]
        return text.strip()

    @classmethod
    def _clean_category_entries(
        cls, category_entries: dict[str, list[tuple[int, int, str]]]
    ) -> dict[str, list[tuple[int, int, str]]]:
        return {
            category: [(ds, de, cls._clean_name(name)) for ds, de, name in entries]
            for category, entries in category_entries.items()
        }

    @classmethod
    def _render_gantt_panel(
        cls,
        year: int,
        month: int,
        cleaned_entries: dict[str, list[tuple[int, int, str]]],
    ) -> Image.Image:
        """Draws only a month's Gantt (title + one row per category, colored
        by family, cleaned names) - without the detailed list, so it can be
        composed with other months' Gantts before adding a single detail
        section at the bottom."""

        last_day = calendar_module.monthrange(year, month)[1]
        categories = list(cleaned_entries.keys())

        lanes_by_category: dict[str, list[int]] = {}
        lane_count_by_category: dict[str, int] = {}
        for category, entries in cleaned_entries.items():
            assignment, n_lanes = cls._assign_lanes(entries)
            lanes_by_category[category] = assignment
            lane_count_by_category[category] = n_lanes

        row_heights = [lane_count_by_category[c] * cls.LANE_HEIGHT for c in categories]
        chart_width = last_day * cls.DAY_COL_WIDTH
        chart_height = sum(row_heights)
        canvas_width = cls.PADDING_X + cls.ROW_LABEL_WIDTH + chart_width + cls.PADDING_X
        canvas_height = cls.PADDING_TOP + cls.HEADER_HEIGHT + chart_height + cls.PADDING_BOTTOM

        canvas = Image.new("RGB", (canvas_width, canvas_height), cls.BG_COLOR)
        draw = ImageDraw.Draw(canvas)

        font_title = cls._try_font(cls.TITLE_FONT_SIZE, bold=True)
        font_day = cls._try_font(cls.DAY_FONT_SIZE)
        font_label = cls._try_font(cls.ROW_LABEL_FONT_SIZE, bold=True)
        font_bar = cls._try_font(cls.BAR_FONT_SIZE)

        title = f"{MONTHS_IT.get(month, month)} {year}"
        draw.text((cls.PADDING_X, 20), title, fill=cls.TEXT_PRIMARY, font=font_title)

        chart_x = cls.PADDING_X + cls.ROW_LABEL_WIDTH
        chart_y = cls.PADDING_TOP + cls.HEADER_HEIGHT

        # ── Day header + vertical grid ──
        for day in range(1, last_day + 1):
            x = chart_x + (day - 1) * cls.DAY_COL_WIDTH
            draw.text(
                (x + cls.DAY_COL_WIDTH / 2, cls.PADDING_TOP + cls.HEADER_HEIGHT / 2),
                str(day),
                fill=cls.TEXT_SECONDARY,
                font=font_day,
                anchor="mm",
            )
            is_week_boundary = day % 7 == 1
            line_color = cls.GRID_COLOR_STRONG if is_week_boundary else cls.GRID_COLOR
            draw.line([(x, chart_y), (x, chart_y + chart_height)], fill=line_color, width=1)
        draw.line(
            [(chart_x + chart_width, chart_y), (chart_x + chart_width, chart_y + chart_height)],
            fill=cls.GRID_COLOR_STRONG,
            width=1,
        )

        # ── Category rows + bars (family color, cleaned names) ──
        row_y = chart_y
        for row_idx, category in enumerate(categories):
            row_height = row_heights[row_idx]
            color = cls.FAMILY_COLORS[cls._classify_family(category)]
            lane_assignment = lanes_by_category[category]

            draw.rectangle([cls.PADDING_X, row_y, chart_x, row_y + row_height], fill=cls.ROW_LABEL_BG)
            draw.text(
                (cls.PADDING_X + 10, row_y + row_height / 2),
                category,
                fill=cls.TEXT_PRIMARY,
                font=font_label,
                anchor="lm",
            )
            draw.line(
                [(cls.PADDING_X, row_y + row_height), (chart_x + chart_width, row_y + row_height)],
                fill=cls.GRID_COLOR,
                width=1,
            )

            for entry_idx, (day_start, day_end, name) in enumerate(cleaned_entries[category]):
                lane_y = row_y + lane_assignment[entry_idx] * cls.LANE_HEIGHT
                bar_x1 = chart_x + (day_start - 1) * cls.DAY_COL_WIDTH
                bar_x2 = chart_x + day_end * cls.DAY_COL_WIDTH
                bar_y1 = lane_y + (cls.LANE_HEIGHT - cls.BAR_HEIGHT) / 2
                bar_y2 = bar_y1 + cls.BAR_HEIGHT

                draw.rounded_rectangle([bar_x1 + 2, bar_y1, bar_x2 - 2, bar_y2], radius=5, fill=color)

                bar_width = bar_x2 - bar_x1 - 4
                label = cls._fit_text(draw, name, font_bar, bar_width - 10)
                if label:
                    draw.text(
                        ((bar_x1 + bar_x2) / 2, (bar_y1 + bar_y2) / 2),
                        label,
                        fill=(255, 255, 255),
                        font=font_bar,
                        anchor="mm",
                    )

            row_y += row_height

        return canvas

    @classmethod
    def _build_family_detail(
        cls,
        month: int,
        cleaned_entries: dict[str, list[tuple[int, int, str]]],
    ) -> dict[str, list[tuple[int, int, int, str, str]]]:
        """Groups the (already cleaned) entries by family, for the detailed
        list. Each entry carries its month (even for a single month) so
        _render_detail_section can merge several months without redoing the
        category classification/cleaning."""

        family_detail: dict[str, list[tuple[int, int, int, str, str]]] = {}
        for category, entries in cleaned_entries.items():
            family = cls._classify_family(category)
            clean_category = cls._clean_name(category)
            # Some category names (e.g. "September Format: Magic: The
            # Gathering | The Hobbit Sealed") don't start with the prefix
            # _clean_name() strips, so they stay long - defensive truncation
            # by character (not by pixel: it is secondary text in parentheses
            # in the detailed list, no precision needed).
            if len(clean_category) > cls.DETAIL_CATEGORY_MAX_CHARS:
                clean_category = clean_category[:cls.DETAIL_CATEGORY_MAX_CHARS - 1].rstrip() + "…"

            bucket = family_detail.setdefault(family, [])
            for day_start, day_end, name in entries:
                bucket.append((month, day_start, day_end, name, clean_category))

        return family_detail

    @classmethod
    def _render_detail_section(
        cls,
        family_detail: dict[str, list[tuple[int, int, int, str, str]]],
        width: int,
        show_month: bool,
    ) -> Image.Image:
        """Draws the detailed list (full names, no truncation), grouped by
        family. `show_month` is True when the section merges several months
        (create_multi_month_calendar) - without it, "11-19" of different
        months would be indistinguishable once the lists are merged."""

        families_present = [f for f in cls.FAMILY_ORDER if f in family_detail]

        detail_rows: list[tuple[str, str]] = []  # ("heading"|"item", text)
        for family in families_present:
            detail_rows.append(("heading", family))
            for month, day_start, day_end, name, clean_category in sorted(family_detail[family]):
                date_label = str(day_start) if day_start == day_end else f"{day_start}-{day_end}"
                if show_month:
                    date_label += f" {cls.MONTH_ABBR_IT.get(month, month)}"
                detail_rows.append(("item", f"{date_label}: {name}  ({clean_category})"))

        detail_height = sum(
            cls.DETAIL_HEADING_HEIGHT if kind == "heading" else cls.DETAIL_LINE_HEIGHT
            for kind, _ in detail_rows
        ) + cls.DETAIL_GROUP_GAP * len(families_present)

        canvas = Image.new("RGB", (width, detail_height), cls.BG_COLOR)
        draw = ImageDraw.Draw(canvas)

        font_heading = cls._try_font(cls.DETAIL_HEADING_FONT_SIZE, bold=True)
        font_item = cls._try_font(cls.DETAIL_ITEM_FONT_SIZE)

        y = 0
        for kind, text in detail_rows:
            if kind == "heading":
                color = cls.FAMILY_COLORS[text]
                draw.rounded_rectangle([cls.PADDING_X, y + 4, cls.PADDING_X + 12, y + 16], radius=3, fill=color)
                draw.text((cls.PADDING_X + 20, y), text, fill=cls.TEXT_PRIMARY, font=font_heading)
                y += cls.DETAIL_HEADING_HEIGHT
            else:
                draw.text((cls.PADDING_X + 28, y), text, fill=cls.DETAIL_ITEM_COLOR, font=font_item)
                y += cls.DETAIL_LINE_HEIGHT

        return canvas

    @classmethod
    def _stack_vertically(cls, images: list[Image.Image], gap: int) -> Image.Image:
        width = max(img.width for img in images)
        height = sum(img.height for img in images) + gap * (len(images) - 1)
        canvas = Image.new("RGB", (width, height), cls.BG_COLOR)
        y = 0
        for img in images:
            canvas.paste(img, (0, y))
            y += img.height + gap
        return canvas

    @classmethod
    def create_month_calendar(
        cls,
        year: int,
        month: int,
        category_entries: dict[str, list[tuple[int, int, str]]],
    ) -> BytesIO:
        """Gantt with one row per category (colored by family, cleaned names)
        + detailed list below (full names, category in parentheses) - see the
        module docstring for the iterations that led to this design."""

        cleaned_entries = cls._clean_category_entries(category_entries)

        gantt_img = cls._render_gantt_panel(year, month, cleaned_entries)
        family_detail = cls._build_family_detail(month, cleaned_entries)
        detail_img = cls._render_detail_section(family_detail, width=gantt_img.width, show_month=False)

        canvas = cls._stack_vertically([gantt_img, detail_img], gap=30)

        output = BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        output.seek(0)
        return output
