import pytest
from dataclasses import dataclass
from services.pairing_engine import PairingEngine, PlayerStanding, Pairing


@dataclass
class MockPlayer:
    id: int
    dropped: bool = False
    seed: int = 0


@dataclass
class MockMatch:
    player1_id: int
    player2_id: int | None
    winner_id: int | None = None
    result: str | None = None
    round_number: int = 1
    table_number: int = 1


class TestCalculateRounds:

    def test_un_giocatore(self):
        assert PairingEngine.calculate_rounds(1) == 1

    def test_due_giocatori(self):
        assert PairingEngine.calculate_rounds(2) == 1

    def test_quattro_giocatori(self):
        assert PairingEngine.calculate_rounds(4) == 2

    def test_otto_giocatori(self):
        assert PairingEngine.calculate_rounds(8) == 3

    def test_nove_giocatori(self):
        assert PairingEngine.calculate_rounds(9) == 4


class TestScoreboard:

    def test_vittoria_e_sconfitta(self):
        players = [MockPlayer(1), MockPlayer(2)]
        matches = [
            MockMatch(player1_id=1, player2_id=2, winner_id=1),
        ]
        standings = PairingEngine._scoreboard(players, matches)
        assert standings[1].score == 3.0
        assert standings[2].score == 0.0

    def test_pareggio(self):
        players = [MockPlayer(1), MockPlayer(2)]
        matches = [
            MockMatch(player1_id=1, player2_id=2, result="draw"),
        ]
        standings = PairingEngine._scoreboard(players, matches)
        assert standings[1].score == 1.0
        assert standings[2].score == 1.0

    def test_bye(self):
        players = [MockPlayer(1), MockPlayer(2)]
        matches = [
            MockMatch(player1_id=1, player2_id=None, winner_id=1),
        ]
        standings = PairingEngine._scoreboard(players, matches)
        assert standings[1].score == 3.0
        assert standings[2].score == 0.0

    def test_omw_floor_al_33(self):
        players = [MockPlayer(1), MockPlayer(2)]
        matches = [
            MockMatch(player1_id=1, player2_id=2, winner_id=1),
        ]
        standings = PairingEngine._scoreboard(players, matches)
        p1_omw = standings[1].opponent_win_percent
        assert p1_omw == 0.33


class TestExistingPairs:

    def test_coppia_ordinata(self):
        matches = [
            MockMatch(player1_id=5, player2_id=3),
        ]
        pairs = PairingEngine._existing_pairs(matches)
        assert (3, 5) in pairs
        assert (5, 3) not in pairs

    def test_bye_non_incluso(self):
        matches = [
            MockMatch(player1_id=1, player2_id=None),
        ]
        pairs = PairingEngine._existing_pairs(matches)
        assert len(pairs) == 0


class TestByeHistory:

    def test_bye_tracking(self):
        matches = [
            MockMatch(player1_id=1, player2_id=None),
            MockMatch(player1_id=2, player2_id=3),
        ]
        bye = PairingEngine._bye_history(matches)
        assert 1 in bye
        assert 2 not in bye

    def test_multi_bye(self):
        matches = [
            MockMatch(player1_id=1, player2_id=None),
            MockMatch(player1_id=2, player2_id=None),
        ]
        bye = PairingEngine._bye_history(matches)
        assert len(bye) == 2


class TestGenerateRound:

    def test_round1_quattro_giocatori(self):
        players = [MockPlayer(1), MockPlayer(2), MockPlayer(3), MockPlayer(4)]
        matches = []
        pairings = PairingEngine.generate_round(players, matches, round_number=1)
        assert len(pairings) == 2
        paired_ids = {p.player1_id for p in pairings} | {p.player2_id for p in pairings}
        assert paired_ids == {1, 2, 3, 4}

    def test_round2_evita_rematch(self):
        players = [MockPlayer(1), MockPlayer(2), MockPlayer(3), MockPlayer(4)]
        matches = [
            MockMatch(player1_id=1, player2_id=2, winner_id=1),
            MockMatch(player1_id=3, player2_id=4, winner_id=3),
        ]
        pairings = PairingEngine.generate_round(players, matches, round_number=2)
        assert len(pairings) == 2
        for p in pairings:
            a, b = (p.player1_id, p.player2_id) if p.player1_id < p.player2_id else (p.player2_id, p.player1_id)
            assert (a, b) not in {(1, 2), (3, 4)}

    def test_numero_dispari_da_bye(self):
        players = [MockPlayer(1), MockPlayer(2), MockPlayer(3)]
        matches = []
        pairings = PairingEngine.generate_round(players, matches, round_number=1)
        bye_pairings = [p for p in pairings if p.player2_id is None]
        normal_pairings = [p for p in pairings if p.player2_id is not None]
        assert len(bye_pairings) == 1
        assert len(normal_pairings) == 1

    def test_giocatori_droppati_esclusi(self):
        players = [
            MockPlayer(1, dropped=False),
            MockPlayer(2, dropped=False),
            MockPlayer(3, dropped=True),
        ]
        matches = []
        pairings = PairingEngine.generate_round(players, matches, round_number=1)
        paired_ids = set()
        for p in pairings:
            paired_ids.add(p.player1_id)
            if p.player2_id is not None:
                paired_ids.add(p.player2_id)
        assert 3 not in paired_ids

    def test_stesso_giocatore_non_ha_bye_ripetuto(self):
        players = [MockPlayer(1), MockPlayer(2), MockPlayer(3)]
        matches = [
            MockMatch(player1_id=1, player2_id=None, winner_id=1),
            MockMatch(player1_id=2, player2_id=3, winner_id=2),
        ]
        pairings = PairingEngine.generate_round(players, matches, round_number=2)
        bye_players = [p.player1_id for p in pairings if p.player2_id is None]
        assert 1 not in bye_players
