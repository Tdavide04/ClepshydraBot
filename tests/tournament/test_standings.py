from dataclasses import dataclass

from services.standings import StandingsCalculator


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
    def test_omw_minimum_33(self):
        players = [MockPlayer(1), MockPlayer(2), MockPlayer(3), MockPlayer(4)]
        matches = [
            MockMatch(player1_id=1, player2_id=2, winner_id=1, result="win"),
            MockMatch(player1_id=1, player2_id=3, winner_id=1, result="win"),
            MockMatch(player1_id=1, player2_id=4, winner_id=1, result="win"),
        ]
        entries = StandingsCalculator.compute(1, players, matches, get_name, get_deck)
        alice = next(e for e in entries if e.player_id == 1)
        assert alice.opponent_win_percent == 0.33

    def test_omw_without_opponents(self):
        players = [MockPlayer(1)]
        matches = []

        entries = StandingsCalculator.compute(1, players, matches, get_name, get_deck)
        alice = next(e for e in entries if e.player_id == 1)
        assert alice.opponent_win_percent == 0.0

    def test_omw_bye_does_not_count(self):
        players = [MockPlayer(1), MockPlayer(2), MockPlayer(3)]
        matches = [
            MockMatch(player1_id=1, player2_id=3, winner_id=1, result="win"),
            MockMatch(player1_id=2, player2_id=None, winner_id=2, result="win"),
        ]
        entries = StandingsCalculator.compute(1, players, matches, get_name, get_deck)
        p1 = next(e for e in entries if e.player_id == 1)
        p2 = next(e for e in entries if e.player_id == 2)
        assert p1.opponent_win_percent > 0.0
        assert p2.opponent_win_percent == 0.0

    def test_omw_formula_correct(self):
        players = [MockPlayer(1), MockPlayer(2), MockPlayer(3)]
        matches = [
            MockMatch(player1_id=1, player2_id=2, winner_id=1, result="win"),
            MockMatch(player1_id=1, player2_id=3, winner_id=1, result="win"),
            MockMatch(player1_id=2, player2_id=3, winner_id=2, result="win"),
        ]
        entries = StandingsCalculator.compute(1, players, matches, get_name, get_deck)
        p1 = next(e for e in entries if e.player_id == 1)
        p2_wins_2 = 1  # player 2 has 1 win (against 3)
        p2_matches_2 = 2  # played 2 matches (against 1 and 3)
        p2_ratio = max(p2_wins_2 / p2_matches_2, 0.33)
        p3_wins_3 = 0
        p3_matches_3 = 2
        p3_ratio = max(p3_wins_3 / p3_matches_3, 0.33)
        expected = round((p2_ratio + p3_ratio) / 2, 4)
        assert p1.opponent_win_percent == expected


class TestSortStandings:
    def test_sorted_by_points(self):
        players = [MockPlayer(1), MockPlayer(2)]
        matches = [
            MockMatch(player1_id=1, player2_id=2, winner_id=1, result="win"),
        ]

        entries = StandingsCalculator.compute(1, players, matches, get_name, get_deck)
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

        entries = StandingsCalculator.compute(1, players, matches, get_name, get_deck)

        for e in entries:
            if e.player_id == 1:
                assert e.rank == 1
            elif e.player_id == 3:
                assert e.points == 3.0

    def test_tiebreaker_name(self):
        players = [MockPlayer(2), MockPlayer(1)]
        matches = []

        entries = StandingsCalculator.compute(1, players, matches, get_name, get_deck)
        assert entries[0].player_id == 1
        assert entries[1].player_id == 2


class TestDroppedPlayers:
    def test_match_against_player_missing_from_list_does_not_crash(self):
        """Regression: get_standings() passed only active registrations, but
        the matches a dropped player played remain - KeyError on /classifica."""
        players = [MockPlayer(2)]
        matches = [MockMatch(player1_id=1, player2_id=2, winner_id=2, result="win")]

        entries = StandingsCalculator.compute(1, players, matches, get_name, get_deck)

        assert [(e.player_id, e.points) for e in entries] == [(2, 3)]

    def test_dropped_flag_is_propagated(self):
        players = [MockPlayer(1, dropped=True), MockPlayer(2)]
        matches = [MockMatch(player1_id=1, player2_id=2, winner_id=1, result="win")]

        entries = StandingsCalculator.compute(1, players, matches, get_name, get_deck)

        by_id = {e.player_id: e for e in entries}
        assert by_id[1].dropped is True
        assert by_id[2].dropped is False


class TestPendingMatches:
    def test_unplayed_match_does_not_change_standings(self):
        """Regression: a current-round match with no result yet counted as a
        1-1 in games and its opponent entered the OMW, so /classifica
        mid-round skewed GWP and OMW."""
        players = [MockPlayer(1), MockPlayer(2), MockPlayer(3), MockPlayer(4)]
        played = [
            MockMatch(player1_id=1, player2_id=2, winner_id=1, result="win", p1_game_wins=2, p2_game_wins=1),
            MockMatch(player1_id=3, player2_id=4, winner_id=3, result="win", p1_game_wins=2, p2_game_wins=0),
        ]
        pending = MockMatch(player1_id=1, player2_id=3, round_number=2)

        before = StandingsCalculator.compute(1, players, played, get_name, get_deck)
        after = StandingsCalculator.compute(1, players, played + [pending], get_name, get_deck)

        assert after == before

    def test_bye_still_counts_while_pending(self):
        players = [MockPlayer(1)]
        bye = MockMatch(player1_id=1, player2_id=None)

        entries = StandingsCalculator.compute(1, players, [bye], get_name, get_deck)

        assert entries[0].points == 3
