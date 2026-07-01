import math
import random
from dataclasses import dataclass


POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0
POINTS_BYE = 3


@dataclass
class PlayerStanding:
    player_id: int
    seed: int
    score: float
    opponent_wins: float
    game_win_percent: float
    opponent_game_win_percent: float


@dataclass
class Pairing:
    player1_id: int
    player2_id: int | None
    table_number: int


class PairingEngine:

    @staticmethod
    def calculate_rounds(player_count: int) -> int:
        return max(1, math.ceil(math.log2(player_count)))

    @staticmethod
    def _compute_scores(
        players: list,
        matches: list,
    ) -> dict[int, PlayerStanding]:
        scores: dict[int, float] = {}
        for p in players:
            pid = p.id if hasattr(p, "id") else p
            scores[pid] = 0.0

        match_records: dict[int, list[bool | None]] = {}
        for p in players:
            pid = p.id if hasattr(p, "id") else p
            match_records[pid] = []

        for m in matches:
            if m.winner_id is not None:
                scores[m.winner_id] += POINTS_WIN
                loser = (
                    m.player1_id if m.player2_id == m.winner_id
                    else m.player2_id
                )
                if loser is not None:
                    scores[loser] += POINTS_LOSS
                    match_records[m.winner_id].append(True)
                    match_records[loser].append(False)
            elif m.result is not None:
                if m.player1_id is not None:
                    scores[m.player1_id] += POINTS_DRAW
                    match_records[m.player1_id].append(None)
                if m.player2_id is not None:
                    scores[m.player2_id] += POINTS_DRAW
                    match_records[m.player2_id].append(None)
            elif m.player2_id is None:
                if m.player1_id is not None:
                    scores[m.player1_id] += POINTS_BYE
                    match_records[m.player1_id].append(True)

        standings: dict[int, PlayerStanding] = {}
        for p in players:
            pid = p.id if hasattr(p, "id") else p
            pseed = p.seed if hasattr(p, "seed") else 0

            ow = sum(
                scores.get(m.winner_id if m.winner_id != pid else (
                    m.player1_id if m.player2_id == pid else m.player2_id
                ), 0.0)
                for m in matches
                if m.player1_id == pid or m.player2_id == pid
            )
            standings[pid] = PlayerStanding(
                player_id=pid,
                seed=pseed,
                score=scores.get(pid, 0.0),
                opponent_wins=ow,
                game_win_percent=0.5,
                opponent_game_win_percent=0.5,
            )
        return standings

    @staticmethod
    def generate_round(
        players: list,
        matches: list,
        round_number: int,
    ) -> list[Pairing]:
        active = [p for p in players if not getattr(p, "dropped", False)]
        standings = PairingEngine._compute_scores(active, matches)
        existing = PairingEngine._get_existing_pairs(matches)

        sorted_players = sorted(
            active,
            key=lambda p: (
                -standings[p.id].score,
                -standings[p.id].opponent_wins,
                -(p.seed or 0),
            )
        )

        if round_number == 1:
            random.shuffle(sorted_players)

        pairings: list[Pairing] = []
        used: set[int] = set()
        table = 1

        for i in range(len(sorted_players)):
            pid = sorted_players[i].id if hasattr(sorted_players[i], "id") else sorted_players[i]
            if pid in used:
                continue

            opponent = PairingEngine._find_opponent(
                sorted_players, i, used, existing, standings
            )

            if opponent is not None:
                pairings.append(Pairing(
                    player1_id=pid,
                    player2_id=opponent,
                    table_number=table,
                ))
                used.add(pid)
                used.add(opponent)
                table += 1

        remaining = [p for p in sorted_players if (
            p.id if hasattr(p, "id") else p
        ) not in used]
        for p in remaining:
            pid = p.id if hasattr(p, "id") else p
            pairings.append(Pairing(
                player1_id=pid,
                player2_id=None,
                table_number=table,
            ))
            table += 1

        return pairings

    @staticmethod
    def _get_existing_pairs(
        matches: list,
    ) -> set[tuple[int, int]]:
        pairs: set[tuple[int, int]] = set()
        for m in matches:
            if m.player1_id and m.player2_id:
                a, b = m.player1_id, m.player2_id
                pairs.add((a, b) if a < b else (b, a))
        return pairs

    @staticmethod
    def _find_opponent(
        sorted_players: list,
        current_idx: int,
        used: set[int],
        existing_pairs: set[tuple[int, int]],
        standings: dict[int, PlayerStanding],
    ) -> int | None:
        pid = sorted_players[current_idx].id if hasattr(sorted_players[current_idx], "id") else sorted_players[current_idx]

        for j in range(current_idx + 1, len(sorted_players)):
            opp = sorted_players[j]
            opp_id = opp.id if hasattr(opp, "id") else opp
            if opp_id in used:
                continue

            pair = (pid, opp_id) if pid < opp_id else (opp_id, pid)
            if pair in existing_pairs:
                continue

            return opp_id

        return None
