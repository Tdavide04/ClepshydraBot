"""
calendar_model.py

Pure logic behind the event calendar image (no Pillow, no config): groups the
Wizards events into the four community-facing groups and prepares the
agenda rows that `features.monitors.calendar_image` draws. See
docs/adr/0006-event-calendar-agenda-layout.md.
"""

import re
from dataclasses import dataclass, field

GROUP_LIMITED = "Limited"
GROUP_CONSTRUCTED = "Constructed"
GROUP_METAGAME = "Metagame"
GROUP_OTHER = "Eventi vari"

# Display order of the groups in the image.
GROUP_ORDER = [GROUP_LIMITED, GROUP_CONSTRUCTED, GROUP_METAGAME, GROUP_OTHER]


# Keyword heuristics on the Wizards text, not data coming from the page: the
# page only gives a category ("Midweek Magic", "Other Events") that hosts
# events of any format, so the event name has to decide for those.
_METAGAME_CATEGORY_WORDS = ("metagame", "arena direct", "format:", "championship")
_LIMITED_WORDS = ("draft", "sealed", "cube")
_CONSTRUCTED_WORDS = (
    "standard",
    "historic",
    "pioneer",
    "pauper",
    "brawl",
    "artisan",
    "artesian",
    "gladiator",
    "explorer",
    "timeless",
    "alchemy",
)


def classify_event(name: str, category: str) -> str:
    """Returns the group of an event. The category wins for the competitive
    ones (an Arena Direct about a Draft product is still Arena Direct) and for
    the Limited categories ("Flashback Premier Draft"); a generic category
    falls back on the event name. Anything unrecognized is GROUP_OTHER."""

    category_l, name_l = category.lower(), name.lower()
    if any(word in category_l for word in _METAGAME_CATEGORY_WORDS):
        return GROUP_METAGAME
    if "flashback" in category_l or any(word in category_l for word in _LIMITED_WORDS):
        return GROUP_LIMITED
    if any(word in name_l for word in _LIMITED_WORDS):
        return GROUP_LIMITED
    if any(word in name_l for word in _CONSTRUCTED_WORDS):
        return GROUP_CONSTRUCTED
    return GROUP_OTHER


@dataclass(frozen=True)
class AgendaRow:
    start_day: int
    end_day: int
    name: str
    categories: tuple[str, ...]


@dataclass
class Agenda:
    groups: dict[str, list[AgendaRow]] = field(default_factory=dict)
    # Names of the events that fell into GROUP_OTHER because no keyword
    # matched: the caller logs them so a new format gets noticed.
    unclassified: list[str] = field(default_factory=list)


_MTG_PREFIX = re.compile(r"magic: the gathering \| ", re.IGNORECASE)
_ARENA_DIRECT_PREFIX = re.compile(r"^arena direct for ", re.IGNORECASE)


def clean_text(text: str) -> str:
    """Drops the noise Wizards repeats in names and categories: the color
    group already says what kind of event it is, so "Magic: The Gathering | "
    (anywhere) and a leading "Arena Direct for " only cost space."""

    text = _ARENA_DIRECT_PREFIX.sub("", text.strip())
    return _MTG_PREFIX.sub("", text).strip()


def build_agenda(category_entries: dict[str, list[tuple[int, int, str]]]) -> Agenda:
    """Turns {category: [(start_day, end_day, name)]} into agenda rows per
    group. The same event listed under several categories with the same dates
    ("Star Trek" in Premier, Pick-Two and Traditional Draft) becomes one row
    that carries all its categories."""

    merged: dict[tuple[str, int, int, str], list[str]] = {}
    for category, entries in category_entries.items():
        clean_category = clean_text(category)
        for start_day, end_day, raw_name in entries:
            name = clean_text(raw_name)
            group = classify_event(name, clean_category)
            categories = merged.setdefault((group, start_day, end_day, name), [])
            if clean_category not in categories:
                categories.append(clean_category)

    agenda = Agenda()
    for group in GROUP_ORDER:
        rows = [
            AgendaRow(start_day, end_day, name, tuple(categories))
            for (row_group, start_day, end_day, name), categories in merged.items()
            if row_group == group
        ]
        if not rows:
            continue
        rows.sort(key=lambda row: (row.start_day, row.end_day, row.name))
        agenda.groups[group] = rows
        if group == GROUP_OTHER:
            for row in rows:
                if row.name not in agenda.unclassified:
                    agenda.unclassified.append(row.name)
    return agenda
