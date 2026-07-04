from dataclasses import dataclass, field
from database.models import MatchResult


POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0
POINTS_BYE = 3
MWP_FLOOR = 0.33
GWP_FLOOR = 0.33


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
    game_win_percent: float = 0.0
    opponent_game_win_percent: float = 0.0


@dataclass
class _PlayerStats:
    match_wins: int = 0
    match_losses: int = 0
    match_draws: int = 0
    match_points: float = 0.0
    game_wins: int = 0
    game_losses: int = 0
    game_draws: int = 0
    opponents: list[int] = field(default_factory=list)


class StandingsCalculator:

    @staticmethod
    def _get_game_wins(m, pid: int) -> tuple[int, int]:
        if m.player1_id == pid:
            gw = m.p1_game_wins
            gl = m.p2_game_wins
        else:
            gw = m.p2_game_wins
            gl = m.p1_game_wins
        if gw is None or gl is None:
            if m.winner_id == pid:
                return 2, 0
            if m.winner_id is not None:
                return 0, 2
            return 1, 1
        return gw, gl

    @staticmethod
    def compute(
        tournament_id: int,
        players: list,
        matches: list,
        get_player_name: callable,
        get_deck_name: callable = lambda _: "",
    ) -> list[StandingsEntry]:
        stats: dict[int, _PlayerStats] = {}

        for p in players:
            pid = p.id if hasattr(p, "id") else p
            stats[pid] = _PlayerStats()

        for m in matches:
            if m.player2_id is None:
                if m.player1_id is not None:
                    s = stats[m.player1_id]
                    s.match_points += POINTS_BYE
                    s.match_wins += 1
                    s.game_wins += 2
                continue

            if m.player1_id is None or m.player2_id is None:
                continue

            s1 = stats[m.player1_id]
            s2 = stats[m.player2_id]
            s1.opponents.append(m.player2_id)
            s2.opponents.append(m.player1_id)

            gw1, gl1 = StandingsCalculator._get_game_wins(m, m.player1_id)
            gw2, gl2 = StandingsCalculator._get_game_wins(m, m.player2_id)
            s1.game_wins += gw1
            s1.game_losses += gl1
            s2.game_wins += gw2
            s2.game_losses += gl2

            if m.winner_id == m.player1_id:
                s1.match_points += POINTS_WIN
                s1.match_wins += 1
                s2.match_points += POINTS_LOSS
                s2.match_losses += 1
            elif m.winner_id == m.player2_id:
                s2.match_points += POINTS_WIN
                s2.match_wins += 1
                s1.match_points += POINTS_LOSS
                s1.match_losses += 1
            elif m.result is not None:
                s1.match_points += POINTS_DRAW
                s1.match_draws += 1
                s2.match_points += POINTS_DRAW
                s2.match_draws += 1

        def mwp(pid: int) -> float:
            s = stats[pid]
            total = s.match_wins + s.match_losses + s.match_draws
            if total == 0:
                return MWP_FLOOR
            return max(MWP_FLOOR, s.match_wins / total)

        def gwp(pid: int) -> float:
            s = stats[pid]
            total = s.game_wins + s.game_losses + s.game_draws
            if total == 0:
                return GWP_FLOOR
            return max(GWP_FLOOR, s.game_wins / total)

        entries = []
        for p in players:
            pid = p.id if hasattr(p, "id") else p
            s = stats[pid]

            omw = 0.0
            opps = s.opponents
            if opps:
                omw = sum(mwp(oid) for oid in opps) / len(opps)

            ogw = 0.0
            if opps:
                ogw = sum(gwp(oid) for oid in opps) / len(opps)

            entries.append(StandingsEntry(
                rank=0,
                player_id=pid,
                player_name=get_player_name(pid),
                deck_name=get_deck_name(pid),
                points=s.match_points,
                wins=s.match_wins,
                losses=s.match_losses,
                draws=s.match_draws,
                opponent_win_percent=round(omw, 4),
                game_win_percent=round(gwp(pid), 4),
                opponent_game_win_percent=round(ogw, 4),
            ))

        entries.sort(
            key=lambda e: (
                -e.points,
                -e.opponent_win_percent,
                -e.game_win_percent,
                -e.opponent_game_win_percent,
                e.player_name,
            )
        )

        for i, entry in enumerate(entries, 1):
            entry.rank = i

        return entries
