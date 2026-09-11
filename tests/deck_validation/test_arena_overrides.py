import asyncio
import json

import pytest

import utils.arena_overrides as arena_overrides

SEARCH_URL = "https://api.scryfall.com/cards/search?q=set%3Aspg&unique=prints"


@pytest.fixture(autouse=True)
def isolated_overrides(tmp_path, monkeypatch):
    """Ogni test parte da un JSON e una cache in-memory puliti, con un lock
    fresco (asyncio.Lock() creato fuori da un event loop e' sicuro dal
    3.10 in poi, ma ricrearlo evita comunque di condividere stato tra test
    che girano su asyncio.run() separati)."""
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
    """Mocka solo la ricerca 'set:spg' (elenco carte + oracle_id)."""

    async def fake_scryfall_get(session, url, label, retries=5):
        calls.append(url)
        return search_response if url == SEARCH_URL else None

    monkeypatch.setattr(arena_overrides, "_scryfall_get", fake_scryfall_get)


def _install_fake_prints_batch(monkeypatch, printings_by_oracle: dict, batch_calls: list):
    """Mocka _fetch_prints_by_oracle_ids direttamente (non l'HTTP sottostante):
    lascia alla funzione reale sotto test la responsabilita' di dividere in
    batch e di aggregare i risultati, testabile senza dover costruire query
    URL combinate finte."""

    async def fake_fetch(session, oracle_ids):
        batch_calls.append(list(oracle_ids))
        return {oid: printings_by_oracle.get(oid, []) for oid in oracle_ids}

    monkeypatch.setattr(arena_overrides, "_fetch_prints_by_oracle_ids", fake_fetch)


def run(coro):
    return asyncio.run(coro)


ORACLE_A = "oracle-a"
ORACLE_B = "oracle-b"
ORACLE_C = "oracle-c"

# Card A: rara su Arena, common su carta -> qualifica per l'override.
# Card B: rara sia su Arena che su carta -> nessun override, ma va comunque
# segnata come controllata (altrimenti verrebbe ri-scaricata ogni volta).
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

        assert added == [], "nessuna carta nuova: il secondo giro non deve trovare override"
        assert batch_calls == [], "Card A e Card B sono gia' state valutate, nessun batch da fare"

    def test_new_card_in_set_is_picked_up_incrementally(self, monkeypatch):
        search_calls, batch_calls = [], []
        _install_fake_search(monkeypatch, BASE_SEARCH, search_calls)
        _install_fake_prints_batch(monkeypatch, BASE_PRINTINGS, batch_calls)
        run(arena_overrides.update_spg_overrides())

        # Simula l'uscita di una nuova ondata SPG: la ricerca ora include
        # anche una terza carta, mai vista prima.
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
        assert batch_calls == [[ORACLE_C]], "solo Card C (nuova) deve finire in un batch"

        with open(arena_overrides.DATA_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert sorted(on_disk["checked_cards"]["SPG"]) == ["Card A", "Card B", "Card C"]

    def test_legacy_processed_sets_format_does_not_block_a_real_scan(self, monkeypatch):
        """Regressione per il bug scoperto in produzione: un JSON vecchio con
        processed_sets=["SPG"] (e nessun checked_cards) NON deve piu' bloccare
        ogni scansione futura per sempre."""
        legacy_data = {"processed_sets": ["SPG"], "overrides": {}}
        with open(arena_overrides.DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(legacy_data, f)
        arena_overrides._override_cache = None

        search_calls, batch_calls = [], []
        _install_fake_search(monkeypatch, BASE_SEARCH, search_calls)
        _install_fake_prints_batch(monkeypatch, BASE_PRINTINGS, batch_calls)

        added = run(arena_overrides.update_spg_overrides())

        assert added == [("Card A", "common")], "il formato legacy non deve saltare la scansione"
        assert {oid for batch in batch_calls for oid in batch} == {ORACLE_A, ORACLE_B}


class TestPrintsBatching:

    def test_unchecked_cards_are_split_into_batches_of_configured_size(self, monkeypatch):
        """Con piu' carte non valutate di _PRINTS_BATCH_SIZE, la scansione
        deve dividerle in piu' chiamate batch invece di farne una per carta
        (il motivo dell'intero redesign: una richiesta prints_search_uri per
        carta causava tempeste di 429 su scan grandi, osservato in
        produzione dopo la migrazione da processed_sets a checked_cards)."""
        batch_size = arena_overrides._PRINTS_BATCH_SIZE
        n_cards = batch_size + 5

        cards = [_card_row(f"Card {i}", f"oracle-{i}") for i in range(n_cards)]
        search_response = _search_response(*cards)
        printings = {
            f"oracle-{i}": [_printing("rare", ["arena"], "spg", f"oracle-{i}")]
            for i in range(n_cards)
        }

        search_calls, batch_calls = [], []
        _install_fake_search(monkeypatch, search_response, search_calls)
        _install_fake_prints_batch(monkeypatch, printings, batch_calls)

        run(arena_overrides.update_spg_overrides())

        assert len(batch_calls) == 2, "n_cards supera di poco un batch: devono servirne esattamente 2"
        assert len(batch_calls[0]) == batch_size
        assert len(batch_calls[1]) == 5

    def test_failed_batch_does_not_mark_its_cards_as_checked(self, monkeypatch):
        """Se _fetch_prints_by_oracle_ids fallisce per un intero batch (dict
        vuoto, stesso segnale di errore usato per un singolo fetch fallito
        nel design precedente), le carte di quel batch non vanno segnate
        come controllate - vanno ritentate al prossimo giro."""
        search_calls = []
        _install_fake_search(monkeypatch, BASE_SEARCH, search_calls)

        async def failing_fetch(session, oracle_ids):
            return {}  # batch fallito

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
        assert len(calls) == 2, "deve seguire next_page per raccogliere tutte le pagine del batch"

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
        """Regressione per un comportamento verificato dal vivo contro
        Scryfall: una query con oracleid ripetuti (`oracleid:X or
        oracleid:X`) fa tornare risultati incompleti (alcune carte mancanti,
        senza errore esplicito). I duplicati capitano sempre in pratica,
        perche' la ricerca 'set:spg unique=prints' a monte elenca una riga
        per stampa, non per carta."""
        urls_requested = []

        async def fake_scryfall_get(session, url, label, retries=5):
            urls_requested.append(url)
            return {"data": [_printing("rare", ["arena"], "spg", ORACLE_A)], "next_page": None}

        monkeypatch.setattr(arena_overrides, "_scryfall_get", fake_scryfall_get)

        run(arena_overrides._fetch_prints_by_oracle_ids(None, [ORACLE_A, ORACLE_A, ORACLE_A]))

        assert len(urls_requested) == 1
        assert urls_requested[0].count("oracleid") == 1, "il termine per ORACLE_A deve comparire una sola volta nella query"
