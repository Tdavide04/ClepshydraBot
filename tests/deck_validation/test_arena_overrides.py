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


def _card_row(name: str, prints_uri: str) -> dict:
    return {"name": name, "prints_search_uri": prints_uri}


def _printing(rarity: str, games: list, set_code: str = "spg") -> dict:
    return {"rarity": rarity, "games": games, "set": set_code}


def _search_response(*cards: dict) -> dict:
    return {"data": list(cards), "next_page": None}


def _prints_response(*printings: dict) -> dict:
    return {"data": list(printings)}


def _install_fake_scryfall(monkeypatch, responses: dict, calls: list):
    async def fake_scryfall_get(session, url, label, retries=5):
        calls.append(url)
        return responses.get(url)
    monkeypatch.setattr(arena_overrides, "_scryfall_get", fake_scryfall_get)


def run(coro):
    return asyncio.run(coro)


CARD_A_PRINTS = "https://fake.scryfall/card-a/prints"
CARD_B_PRINTS = "https://fake.scryfall/card-b/prints"
CARD_C_PRINTS = "https://fake.scryfall/card-c/prints"

# Card A: rara su Arena, common su carta -> qualifica per l'override.
# Card B: rara sia su Arena che su carta -> nessun override, ma va comunque
# segnata come controllata (altrimenti verrebbe ri-scaricata ogni volta).
BASE_RESPONSES = {
    SEARCH_URL: _search_response(
        _card_row("Card A", CARD_A_PRINTS),
        _card_row("Card B", CARD_B_PRINTS),
    ),
    CARD_A_PRINTS: _prints_response(
        _printing("rare", ["arena"], "spg"),
        _printing("common", ["paper"], "znr"),
    ),
    CARD_B_PRINTS: _prints_response(
        _printing("rare", ["arena"], "spg"),
        _printing("rare", ["paper"], "znr"),
    ),
}


class TestUpdateSpgOverridesIncremental:

    def test_first_scan_adds_overrides_and_tracks_all_checked_cards(self, monkeypatch):
        calls = []
        _install_fake_scryfall(monkeypatch, BASE_RESPONSES, calls)

        added = run(arena_overrides.update_spg_overrides())

        assert added == [("Card A", "common")]
        assert arena_overrides.get_override_rarity("Card A") == "common"
        assert arena_overrides.get_override_rarity("Card B") is None

        with open(arena_overrides.DATA_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["overrides"] == {"Card A": "common"}
        assert sorted(on_disk["checked_cards"]["SPG"]) == ["Card A", "Card B"]

    def test_second_scan_does_not_refetch_already_checked_cards(self, monkeypatch):
        calls = []
        _install_fake_scryfall(monkeypatch, BASE_RESPONSES, calls)
        run(arena_overrides.update_spg_overrides())

        calls.clear()
        added = run(arena_overrides.update_spg_overrides())

        assert added == [], "nessuna carta nuova: il secondo giro non deve trovare override"
        assert CARD_A_PRINTS not in calls, "Card A e' gia' stata valutata, non va ri-scaricata"
        assert CARD_B_PRINTS not in calls, "Card B e' gia' stata valutata, non va ri-scaricata"
        assert SEARCH_URL in calls, "la ricerca del set va comunque rifatta per sapere cosa c'e' di nuovo"

    def test_new_card_in_set_is_picked_up_incrementally(self, monkeypatch):
        calls = []
        _install_fake_scryfall(monkeypatch, BASE_RESPONSES, calls)
        run(arena_overrides.update_spg_overrides())

        # Simula l'uscita di una nuova ondata SPG: la ricerca ora include
        # anche una terza carta, mai vista prima.
        responses_with_new_card = dict(BASE_RESPONSES)
        responses_with_new_card[SEARCH_URL] = _search_response(
            _card_row("Card A", CARD_A_PRINTS),
            _card_row("Card B", CARD_B_PRINTS),
            _card_row("Card C", CARD_C_PRINTS),
        )
        responses_with_new_card[CARD_C_PRINTS] = _prints_response(
            _printing("mythic", ["arena"], "spg"),
            _printing("uncommon", ["paper"], "znr"),
        )
        calls.clear()
        _install_fake_scryfall(monkeypatch, responses_with_new_card, calls)

        added = run(arena_overrides.update_spg_overrides())

        assert added == [("Card C", "uncommon")]
        assert CARD_A_PRINTS not in calls
        assert CARD_B_PRINTS not in calls
        assert CARD_C_PRINTS in calls

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

        calls = []
        _install_fake_scryfall(monkeypatch, BASE_RESPONSES, calls)

        added = run(arena_overrides.update_spg_overrides())

        assert added == [("Card A", "common")], "il formato legacy non deve saltare la scansione"
        assert CARD_A_PRINTS in calls
        assert CARD_B_PRINTS in calls
