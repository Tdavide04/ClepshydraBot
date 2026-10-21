import asyncio
import json

import pytest

import utils.arena_overrides as arena_overrides

SEARCH_URL = "https://api.scryfall.com/cards/search?q=set%3Aspg&unique=prints"


@pytest.fixture(autouse=True)
def isolated_overrides(tmp_path, monkeypatch):
    """Every test starts from a clean JSON and in-memory cache, with a fresh
    lock (an asyncio.Lock() created outside an event loop is safe from 3.10
    on, but recreating it still avoids sharing state between tests that run
    on separate asyncio.run() calls)."""
    monkeypatch.setattr(arena_overrides, "DATA_PATH", str(tmp_path / "arena_rarity_data.json"))
    monkeypatch.setattr(arena_overrides, "_override_cache", None)
    monkeypatch.setattr(arena_overrides, "_update_lock", asyncio.Lock())
    yield


def _card_row(name: str, oracle_id: str) -> dict:
    return {"name": name, "oracle_id": oracle_id}


def _printing(rarity: str, games: list, set_code: str = "spg", oracle_id: str = "") -> dict:
    return {"rarity": rarity, "games": games, "set": set_code, "oracle_id": oracle_id}


def _search_response(*cards: dict) -> dict:
    return {"data": list(cards), "next_page": None}


def _install_fake_search(monkeypatch, search_response: dict, calls: list):
    """Mocks only the 'set:spg' search (card list + oracle_id)."""

    async def fake_scryfall_get(session, url, label, retries=5):
        calls.append(url)
        return search_response if url == SEARCH_URL else None

    monkeypatch.setattr(arena_overrides, "_scryfall_get", fake_scryfall_get)


def _install_fake_prints_batch(monkeypatch, printings_by_oracle: dict, batch_calls: list):
    """Mocks _fetch_prints_by_oracle_ids directly (not the underlying HTTP):
    leaves batching and result aggregation to the real function under test,
    testable without building fake combined query URLs."""

    async def fake_fetch(session, oracle_ids):
        batch_calls.append(list(oracle_ids))
        return {oid: printings_by_oracle.get(oid, []) for oid in oracle_ids}

    monkeypatch.setattr(arena_overrides, "_fetch_prints_by_oracle_ids", fake_fetch)


def run(coro):
    return asyncio.run(coro)


ORACLE_A = "oracle-a"
ORACLE_B = "oracle-b"
ORACLE_C = "oracle-c"

# Card A: rare on Arena, common on paper -> qualifies for the override.
# Card B: rare both on Arena and on paper -> no override, but it must still be
# marked as checked (otherwise it would be downloaded again every time).
BASE_SEARCH = _search_response(
    _card_row("Card A", ORACLE_A),
    _card_row("Card B", ORACLE_B),
)
BASE_PRINTINGS = {
    ORACLE_A: [
        _printing("rare", ["arena"], "spg", ORACLE_A),
        _printing("common", ["paper"], "znr", ORACLE_A),
    ],
    ORACLE_B: [
        _printing("rare", ["arena"], "spg", ORACLE_B),
        _printing("rare", ["paper"], "znr", ORACLE_B),
    ],
}


class TestUpdateSpgOverridesIncremental:
    def test_first_scan_adds_overrides_and_tracks_all_checked_cards(self, monkeypatch):
        search_calls, batch_calls = [], []
        _install_fake_search(monkeypatch, BASE_SEARCH, search_calls)
        _install_fake_prints_batch(monkeypatch, BASE_PRINTINGS, batch_calls)

        added = run(arena_overrides.update_spg_overrides())

        assert added == [("Card A", "common")]
        assert arena_overrides.get_override_rarity("Card A") == "common"
        assert arena_overrides.get_override_rarity("Card B") is None

        with open(arena_overrides.DATA_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["overrides"] == {"Card A": "common"}
        assert sorted(on_disk["checked_cards"]["SPG"]) == ["Card A", "Card B"]

    def test_second_scan_does_not_refetch_already_checked_cards(self, monkeypatch):
        search_calls, batch_calls = [], []
        _install_fake_search(monkeypatch, BASE_SEARCH, search_calls)
        _install_fake_prints_batch(monkeypatch, BASE_PRINTINGS, batch_calls)
        run(arena_overrides.update_spg_overrides())

        batch_calls.clear()
        added = run(arena_overrides.update_spg_overrides())

        assert added == [], "no new card: the second run must not find overrides"
        assert batch_calls == [], "Card A and Card B were already evaluated, no batch to run"

    def test_new_card_in_set_is_picked_up_incrementally(self, monkeypatch):
        search_calls, batch_calls = [], []
        _install_fake_search(monkeypatch, BASE_SEARCH, search_calls)
        _install_fake_prints_batch(monkeypatch, BASE_PRINTINGS, batch_calls)
        run(arena_overrides.update_spg_overrides())

        # Simulates a new SPG wave: the search now also includes a third
        # card, never seen before.
        search_with_new_card = _search_response(
            _card_row("Card A", ORACLE_A),
            _card_row("Card B", ORACLE_B),
            _card_row("Card C", ORACLE_C),
        )
        printings_with_new_card = dict(BASE_PRINTINGS)
        printings_with_new_card[ORACLE_C] = [
            _printing("mythic", ["arena"], "spg", ORACLE_C),
            _printing("uncommon", ["paper"], "znr", ORACLE_C),
        ]
        _install_fake_search(monkeypatch, search_with_new_card, search_calls)
        batch_calls.clear()
        _install_fake_prints_batch(monkeypatch, printings_with_new_card, batch_calls)

        added = run(arena_overrides.update_spg_overrides())

        assert added == [("Card C", "uncommon")]
        assert batch_calls == [[ORACLE_C]], "only Card C (new) must end up in a batch"

        with open(arena_overrides.DATA_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert sorted(on_disk["checked_cards"]["SPG"]) == ["Card A", "Card B", "Card C"]

    def test_legacy_processed_sets_format_does_not_block_a_real_scan(self, monkeypatch):
        """Regression for the bug found in production: an old JSON with
        processed_sets=["SPG"] (and no checked_cards) must NOT block every
        future scan forever anymore."""
        legacy_data = {"processed_sets": ["SPG"], "overrides": {}}
        with open(arena_overrides.DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(legacy_data, f)
        arena_overrides._override_cache = None

        search_calls, batch_calls = [], []
        _install_fake_search(monkeypatch, BASE_SEARCH, search_calls)
        _install_fake_prints_batch(monkeypatch, BASE_PRINTINGS, batch_calls)

        added = run(arena_overrides.update_spg_overrides())

        assert added == [("Card A", "common")], "the legacy format must not skip the scan"
        assert {oid for batch in batch_calls for oid in batch} == {ORACLE_A, ORACLE_B}


class TestOverrideFileSurvivesFailedWrite:
    def test_a_write_interrupted_midway_leaves_the_previous_file_intact(self, monkeypatch):
        """Regression (3.6.6): the override JSON was written in place with open(..., "w"), so a
        failure mid-write (full disk, crash) left a truncated file that broke json.load on the next start.
        The file is curated data tracked in git, so it must survive a failed save untouched."""
        previous = {"overrides": {"Old Card": "common"}, "checked_cards": {"SPG": ["Old Card"]}}
        with open(arena_overrides.DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(previous, f, indent=4, ensure_ascii=False)
        with open(arena_overrides.DATA_PATH, encoding="utf-8") as f:
            previous_text = f.read()

        search_calls, batch_calls = [], []
        _install_fake_search(monkeypatch, BASE_SEARCH, search_calls)
        _install_fake_prints_batch(monkeypatch, BASE_PRINTINGS, batch_calls)

        def write_half_then_fail(obj, fp, **kwargs):
            fp.write('{"overrides": {')
            raise OSError("No space left on device")

        monkeypatch.setattr(json, "dump", write_half_then_fail)

        with pytest.raises(OSError):
            run(arena_overrides.update_spg_overrides())

        with open(arena_overrides.DATA_PATH, encoding="utf-8") as f:
            assert f.read() == previous_text


class TestPrintsBatching:
    def test_unchecked_cards_are_split_into_batches_of_configured_size(self, monkeypatch):
        """With more unevaluated cards than _PRINTS_BATCH_SIZE, the scan must
        split them into several batch calls instead of one per card (the
        reason for the whole redesign: one prints_search_uri request per card
        caused 429 storms on large scans, observed in production after the
        processed_sets -> checked_cards migration)."""
        batch_size = arena_overrides._PRINTS_BATCH_SIZE
        n_cards = batch_size + 5

        cards = [_card_row(f"Card {i}", f"oracle-{i}") for i in range(n_cards)]
        search_response = _search_response(*cards)
        printings = {
            f"oracle-{i}": [_printing("rare", ["arena"], "spg", f"oracle-{i}")] for i in range(n_cards)
        }

        search_calls, batch_calls = [], []
        _install_fake_search(monkeypatch, search_response, search_calls)
        _install_fake_prints_batch(monkeypatch, printings, batch_calls)

        run(arena_overrides.update_spg_overrides())

        assert len(batch_calls) == 2, "n_cards is just over one batch: exactly 2 are needed"
        assert len(batch_calls[0]) == batch_size
        assert len(batch_calls[1]) == 5

    def test_failed_batch_does_not_mark_its_cards_as_checked(self, monkeypatch):
        """If _fetch_prints_by_oracle_ids fails for a whole batch (empty dict,
        the same error signal used for a single failed fetch in the previous
        design), that batch's cards must not be marked as checked - they must
        be retried on the next run."""
        search_calls = []
        _install_fake_search(monkeypatch, BASE_SEARCH, search_calls)

        async def failing_fetch(session, oracle_ids):
            return {}  # failed batch

        monkeypatch.setattr(arena_overrides, "_fetch_prints_by_oracle_ids", failing_fetch)

        added = run(arena_overrides.update_spg_overrides())

        assert added == []
        with open(arena_overrides.DATA_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["checked_cards"].get("SPG", []) == []


class TestFetchPrintsByOracleIds:
    def test_groups_printings_by_oracle_id_across_pages(self, monkeypatch):
        page_1 = {
            "data": [_printing("rare", ["arena"], "spg", ORACLE_A)],
            "next_page": "https://fake.scryfall/page2",
        }
        page_2 = {
            "data": [
                _printing("common", ["paper"], "znr", ORACLE_A),
                _printing("rare", ["arena"], "spg", ORACLE_B),
            ],
            "next_page": None,
        }

        calls = []

        async def fake_scryfall_get(session, url, label, retries=5):
            calls.append(url)
            if "page2" in url:
                return page_2
            return page_1

        monkeypatch.setattr(arena_overrides, "_scryfall_get", fake_scryfall_get)

        grouped = run(arena_overrides._fetch_prints_by_oracle_ids(None, [ORACLE_A, ORACLE_B]))

        assert len(grouped[ORACLE_A]) == 2
        assert len(grouped[ORACLE_B]) == 1
        assert len(calls) == 2, "must follow next_page to collect every page of the batch"

    def test_empty_oracle_id_list_makes_no_request(self, monkeypatch):
        calls = []

        async def fake_scryfall_get(session, url, label, retries=5):
            calls.append(url)
            return {"data": [], "next_page": None}

        monkeypatch.setattr(arena_overrides, "_scryfall_get", fake_scryfall_get)

        grouped = run(arena_overrides._fetch_prints_by_oracle_ids(None, []))

        assert grouped == {}
        assert calls == []

    def test_request_failure_returns_empty_dict_for_the_whole_batch(self, monkeypatch):
        async def failing_scryfall_get(session, url, label, retries=5):
            return None

        monkeypatch.setattr(arena_overrides, "_scryfall_get", failing_scryfall_get)

        grouped = run(arena_overrides._fetch_prints_by_oracle_ids(None, [ORACLE_A]))

        assert grouped == {}

    def test_duplicate_oracle_ids_are_deduplicated_before_querying(self, monkeypatch):
        """Regression for a behavior verified live against Scryfall: a query
        with repeated oracleids (`oracleid:X or oracleid:X`) returns
        incomplete results (some cards missing, with no explicit error).
        Duplicates always happen in practice, because the upstream 'set:spg
        unique=prints' search lists one row per printing, not per card."""
        urls_requested = []

        async def fake_scryfall_get(session, url, label, retries=5):
            urls_requested.append(url)
            return {"data": [_printing("rare", ["arena"], "spg", ORACLE_A)], "next_page": None}

        monkeypatch.setattr(arena_overrides, "_scryfall_get", fake_scryfall_get)

        run(arena_overrides._fetch_prints_by_oracle_ids(None, [ORACLE_A, ORACLE_A, ORACLE_A]))

        assert len(urls_requested) == 1
        assert urls_requested[0].count("oracleid") == 1, (
            "the ORACLE_A term must appear only once in the query"
        )
