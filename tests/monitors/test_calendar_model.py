import pytest

from features.monitors import calendar_model


class TestClassifyEvent:
    @pytest.mark.parametrize(
        ("name", "category"),
        [
            ("Star Trek", "Premier Draft"),
            ("Pioneer Masters", "Flashback Premier Draft"),
            ("Star Trek Traditional Sealed", "Sealed and Traditional Sealed"),
            ("Arena Powered Cube", "Cube"),
            ("Star Trek Omniscience Draft", "Other Events"),
            ("Golden Pack Sealed", "Midweek Magic"),
        ],
    )
    def test_limited(self, name, category):
        assert calendar_model.classify_event(name, category) == "Limited"

    @pytest.mark.parametrize(
        ("name", "category"),
        [
            ("Artisan Brawl", "Midweek Magic"),
            ("Historic Pauper", "Midweek Magic"),
            ("All-Access Standard Rampage", "Other Events"),
            ("Future Standard Challenge (Best-of-One)", "Other Events"),
        ],
    )
    def test_constructed(self, name, category):
        assert calendar_model.classify_event(name, category) == "Constructed"

    @pytest.mark.parametrize(
        ("name", "category"),
        [
            ("Star Trek Collector Booster boxes", "Arena Direct"),
            ("Historic Metagame Challenge", "Metagame Challenge"),
            ("Qualifier Weekend", "November Format: Magic: The Gathering | Star Trek Sealed"),
            ("Arena Limited Championship Qualifier 4", "Arena Limited Championship Events"),
        ],
    )
    def test_metagame(self, name, category):
        assert calendar_model.classify_event(name, category) == "Metagame"

    def test_category_beats_name_keywords(self):
        """An Arena Direct about a Draft product is still Arena Direct (Metagame)."""
        name = "Arena Powered Cube Draft Play Booster boxes"
        assert calendar_model.classify_event(name, "Arena Direct") == "Metagame"

    def test_unrecognized_event_falls_into_other(self):
        assert calendar_model.classify_event("Momir", "Midweek Magic") == "Eventi vari"

    def test_matching_ignores_case(self):
        assert calendar_model.classify_event("HISTORIC PAUPER", "midweek magic") == "Constructed"


class TestBuildAgenda:
    def test_groups_events_and_strips_the_redundant_prefixes(self):
        entries = {
            "Quick Draft": [(7, 18, "Magic: The Gathering | Bloomburrow")],
            "Arena Direct": [(13, 22, "Arena Direct for Star Trek Collector Booster boxes")],
        }

        agenda = calendar_model.build_agenda(entries)

        assert agenda.groups["Limited"] == [calendar_model.AgendaRow(7, 18, "Bloomburrow", ("Quick Draft",))]
        assert agenda.groups["Metagame"][0].name == "Star Trek Collector Booster boxes"

    def test_strips_the_mtg_prefix_in_the_middle_of_a_name_and_in_categories(self):
        entries = {
            "December Format: Magic: The Gathering | Pioneer": [(19, 20, "Qualifier Weekend")],
            "Arena Direct": [(25, 27, "Cube Draft for Magic: The Gathering | Star Trek boxes")],
        }

        agenda = calendar_model.build_agenda(entries)

        assert agenda.groups["Metagame"][0].categories == ("December Format: Pioneer",)
        assert agenda.groups["Metagame"][1].name == "Cube Draft for Star Trek boxes"

    def test_merges_the_same_event_listed_in_several_categories(self):
        entries = {
            "Premier Draft": [(10, 30, "Star Trek")],
            "Pick-Two Draft": [(10, 30, "Star Trek")],
            "Traditional Draft": [(10, 30, "Star Trek")],
        }

        rows = calendar_model.build_agenda(entries).groups["Limited"]

        assert rows == [
            calendar_model.AgendaRow(
                10, 30, "Star Trek", ("Premier Draft", "Pick-Two Draft", "Traditional Draft")
            )
        ]

    def test_does_not_merge_same_name_with_different_dates(self):
        entries = {"Contender Draft": [(10, 13, "Star Trek"), (23, 30, "Star Trek")]}

        rows = calendar_model.build_agenda(entries).groups["Limited"]

        assert [(r.start_day, r.end_day) for r in rows] == [(10, 13), (23, 30)]

    def test_orders_rows_by_start_day_then_end_day_then_name(self):
        entries = {
            "Quick Draft": [(19, 28, "Star Trek"), (7, 18, "Bloomburrow")],
            "Premier Draft": [(7, 12, "Zeta"), (7, 12, "Alpha")],
        }

        rows = calendar_model.build_agenda(entries).groups["Limited"]

        assert [r.name for r in rows] == ["Alpha", "Zeta", "Bloomburrow", "Star Trek"]

    def test_omits_empty_groups(self):
        agenda = calendar_model.build_agenda({"Quick Draft": [(1, 5, "Bloomburrow")]})

        assert list(agenda.groups) == ["Limited"]

    def test_reports_unclassified_event_names_once(self):
        entries = {"Midweek Magic": [(15, 16, "Momir")], "Other Events": [(15, 16, "Momir")]}

        agenda = calendar_model.build_agenda(entries)

        assert agenda.groups["Eventi vari"][0].name == "Momir"
        assert agenda.unclassified == ["Momir"]
