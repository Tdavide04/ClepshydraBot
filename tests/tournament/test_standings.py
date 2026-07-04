from dataclasses import dataclass, field
from services.standings import StandingsCalculator, StandingsEntry


@dataclass
class MockPlayer:
    id: int
    dropped: bool = False


@dataclass
class MockMatch:
    player1_id: int
    player2_id: int | None
    winner_id: int | None = None
    result: str | None = None
    p1_game_wins: int | None = None
    p2_game_wins: int | None = None
    round_number: int = 1
    table_number: int = 1


def get_name(pid: int) -> str:
    names = {1: "Alice", 2: "Bob", 3: "Charlie", 4: "Diana", 5: "Eve"}
    return names.get(pid, f"Player{pid}")


def get_deck(pid: int) -> str:
    decks = {1: "Mono Red", 2: "Azorius", 3: "Gruul", 4: "Dimir", 5: "Selesnya"}
    return decks.get(pid, "")


class TestCalculateOmw:

    def test_omw_minimo_33(self):
        players = [MockPlayer(1), MockPlayer(2), MockPlayer(3), MockPlayer(4)]
        matches = [
            MockMatch(player1_id=1, player2_id=2, winner_id=1, result="win"),
            MockMatch(player1_id=1, player2_id=3, winner_id=1, result="win"),
            MockMatch(player1_id=1, player2_id=4, winner_id=1, result="win"),
        ]
        entries = StandingsCalculator.compute(
            1, players, matches, get_name, get_deck
        )
        alice = next(e for e in entries if e.player_id == 1)
        assert alice.opponent_win_percent == 0.33

    def test_omw_senza_avversari(self):
        players = [MockPlayer(1)]
        matches = []

        entries = StandingsCalculator.compute(
            1, players, matches, get_name, get_deck
        )
        alice = next(e for e in entries if e.player_id == 1)
        assert alice.opponent_win_percent == 0.0

    def test_omw_bye_non_conta(self):
        players = [MockPlayer(1), MockPlayer(2), MockPlayer(3)]
        matches = [
            MockMatch(player1_id=1, player2_id=3, winner_id=1, result="win"),
            MockMatch(player1_id=2, player2_id=None, winner_id=2, result="win"),
        ]
        entries = StandingsCalculator.compute(
            1, players, matches, get_name, get_deck
        )
        p1 = next(e for e in entries if e.player_id == 1)
        p2 = next(e for e in entries if e.player_id == 2)
        assert p1.opponent_win_percent > 0.0
        assert p2.opponent_win_percent == 0.0

    def test_omw_formula_corretta(self):
        players = [MockPlayer(1), MockPlayer(2), MockPlayer(3)]
        matches = [
            MockMatch(player1_id=1, player2_id=2, winner_id=1, result="win"),
            MockMatch(player1_id=1, player2_id=3, winner_id=1, result="win"),
            MockMatch(player1_id=2, player2_id=3, winner_id=2, result="win"),
        ]
        entries = StandingsCalculator.compute(
            1, players, matches, get_name, get_deck
        )
        p1 = next(e for e in entries if e.player_id == 1)
        p2_wins_2 = 1  # player1 2 ha 1 vittoria (contro 3)
        p2_matches_2 = 2  # ha giocato 2 partite (contro 1 e 3)
        p2_ratio = max(p2_wins_2 / p2_matches_2, 0.33)
        p3_wins_3 = 0
        p3_matches_3 = 2
        p3_ratio = max(p3_wins_3 / p3_matches_3, 0.33)
        expected = round((p2_ratio + p3_ratio) / 2, 4)
        assert p1.opponent_win_percent == expected


class TestSortStandings:

    def test_ordinamento_per_punti(self):
        players = [MockPlayer(1), MockPlayer(2)]
        matches = [
            MockMatch(player1_id=1, player2_id=2, winner_id=1, result="win"),
        ]

        entries = StandingsCalculator.compute(
            1, players, matches, get_name, get_deck
        )
        assert entries[0].player_id == 1
        assert entries[0].points == 3.0
        assert entries[1].player_id == 2
        assert entries[1].points == 0.0

    def test_tiebreaker_omw(self):
        players = [MockPlayer(1), MockPlayer(2), MockPlayer(3), MockPlayer(4), MockPlayer(5)]
        matches = [
            MockMatch(player1_id=1, player2_id=2, winner_id=1, result="win"),
            MockMatch(player1_id=3, player2_id=4, winner_id=3, result="win"),
            MockMatch(player1_id=1, player2_id=3, winner_id=1, result="win"),
            MockMatch(player1_id=2, player2_id=4, winner_id=2, result="win"),
            MockMatch(player1_id=5, player2_id=None, winner_id=5, result="win"),
        ]

        entries = StandingsCalculator.compute(
            1, players, matches, get_name, get_deck
        )

        for e in entries:
            if e.player_id == 1:
                assert e.rank == 1
            elif e.player_id == 3:
                assert e.points == 3.0

    def test_tiebreaker_nome(self):
        players = [MockPlayer(2), MockPlayer(1)]
        matches = []

        entries = StandingsCalculator.compute(
            1, players, matches, get_name, get_deck
        )
        assert entries[0].player_id == 1
        assert entries[1].player_id == 2
