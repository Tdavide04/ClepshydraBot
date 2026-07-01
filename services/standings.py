from dataclasses import dataclass
from database.models import MatchResult


POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0
POINTS_BYE = 3


@dataclass
class StandingsEntry:
    rank: int
    player_id: int
    player_name: str
    deck_name: str
    points: float
    wins: int
    losses: int
    draws: int
    opponent_win_percent: float


class StandingsCalculator:

    @staticmethod
    def compute(
        tournament_id: int,
        players: list,
        matches: list,
        get_player_name: callable,
        get_deck_name: callable = lambda _: "",
    ) -> list[StandingsEntry]:
        points: dict[int, float] = {}
        wins: dict[int, int] = {}
        losses: dict[int, int] = {}
        draws: dict[int, int] = {}

        for p in players:
            pid = p.id if hasattr(p, "id") else p
            points[pid] = 0.0
            wins[pid] = 0
            losses[pid] = 0
            draws[pid] = 0

        for m in matches:
            if m.player2_id is None:
                if m.player1_id is not None:
                    points[m.player1_id] += POINTS_BYE
                    wins[m.player1_id] += 1
                continue

            if m.winner_id is not None:
                points[m.winner_id] += POINTS_WIN
                wins[m.winner_id] += 1
                loser = (
                    m.player1_id if m.player2_id == m.winner_id
                    else m.player2_id
                )
                if loser is not None:
                    points[loser] += POINTS_LOSS
                    losses[loser] += 1
            elif m.result is not None:
                if m.player1_id is not None:
                    points[m.player1_id] += POINTS_DRAW
                    draws[m.player1_id] += 1
                if m.player2_id is not None:
                    points[m.player2_id] += POINTS_DRAW
                    draws[m.player2_id] += 1

        total_matches: dict[int, int] = {}
        for p in players:
            pid = p.id if hasattr(p, "id") else p
            total_matches[pid] = wins[pid] + losses[pid] + draws[pid]

        opponent_win_percent: dict[int, float] = {}
        for p in players:
            pid = p.id if hasattr(p, "id") else p
            opponents = []
            for m in matches:
                opp_id = None
                if m.player1_id == pid and m.player2_id is not None:
                    opp_id = m.player2_id
                elif m.player2_id == pid:
                    opp_id = m.player1_id
                if opp_id is not None:
                    opp_total = wins[opp_id] + losses[opp_id] + draws[opp_id]
                    if opp_total > 0:
                        opponents.append(wins[opp_id] / opp_total)
            if opponents:
                opponent_win_percent[pid] = sum(opponents) / len(opponents)
            else:
                opponent_win_percent[pid] = 0.0

        entries = []
        for p in players:
            pid = p.id if hasattr(p, "id") else p
            entries.append(StandingsEntry(
                rank=0,
                player_id=pid,
                player_name=get_player_name(pid),
                deck_name=get_deck_name(pid),
                points=points.get(pid, 0.0),
                wins=wins.get(pid, 0),
                losses=losses.get(pid, 0),
                draws=draws.get(pid, 0),
                opponent_win_percent=opponent_win_percent.get(pid, 0.0),
            ))

        entries.sort(
            key=lambda e: (-e.points, -e.opponent_win_percent, e.player_name)
        )

        for i, entry in enumerate(entries, 1):
            entry.rank = i

        return entries
