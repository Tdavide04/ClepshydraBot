import math
from collections import defaultdict
from dataclasses import dataclass


POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0
POINTS_BYE = 3
MWP_FLOOR = 0.33


@dataclass
class PlayerStanding:
    player_id: int
    seed: int
    score: float
    opponent_win_percent: float


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
    def _scoreboard(players: list, matches: list) -> dict[int, PlayerStanding]:
        points: dict[int, float] = defaultdict(float)
        match_wins: dict[int, int] = defaultdict(int)
        opponents: dict[int, list[int]] = defaultdict(list)

        for p in players:
            pid = p.id if hasattr(p, "id") else p
            points[pid] = 0.0
            match_wins[pid] = 0
            opponents[pid] = []

        for m in matches:
            if m.player2_id is None:
                if m.player1_id is not None:
                    points[m.player1_id] += POINTS_BYE
                    match_wins[m.player1_id] += 1
                continue
            if m.player1_id is None or m.player2_id is None:
                continue

            opponents[m.player1_id].append(m.player2_id)
            opponents[m.player2_id].append(m.player1_id)

            if m.winner_id == m.player1_id:
                points[m.player1_id] += POINTS_WIN
                points[m.player2_id] += POINTS_LOSS
                match_wins[m.player1_id] += 1
            elif m.winner_id == m.player2_id:
                points[m.player2_id] += POINTS_WIN
                points[m.player1_id] += POINTS_LOSS
                match_wins[m.player2_id] += 1
            elif m.result is not None:
                points[m.player1_id] += POINTS_DRAW
                points[m.player2_id] += POINTS_DRAW

        def mwp(pid: int) -> float:
            total_wins = match_wins.get(pid, 0)
            total = sum(
                1 for m in matches
                if (m.player1_id == pid or m.player2_id == pid)
                and m.player2_id is not None
            )
            if total == 0:
                return MWP_FLOOR
            return max(MWP_FLOOR, total_wins / total)

        standings = {}
        for p in players:
            pid = p.id if hasattr(p, "id") else p
            opps = opponents.get(pid, [])
            omw = sum(mwp(o) for o in opps) / len(opps) if opps else 0.0
            standings[pid] = PlayerStanding(
                player_id=pid,
                seed=getattr(p, "seed", 0) or 0,
                score=points.get(pid, 0.0),
                opponent_win_percent=omw,
            )
        return standings

    @staticmethod
    def _existing_pairs(matches: list) -> set[tuple[int, int]]:
        pairs = set()
        for m in matches:
            if m.player1_id and m.player2_id:
                a, b = m.player1_id, m.player2_id
                pairs.add((a, b) if a < b else (b, a))
        return pairs

    @staticmethod
    def _bye_history(matches: list) -> set[int]:
        return {m.player1_id for m in matches if m.player2_id is None}

    @staticmethod
    def generate_round(
        players: list,
        matches: list,
        round_number: int,
    ) -> list[Pairing]:
        active = [p for p in players if not getattr(p, "dropped", False)]
        standings = PairingEngine._scoreboard(active, matches)
        existing = PairingEngine._existing_pairs(matches)
        bye_received = PairingEngine._bye_history(matches)

        brackets = defaultdict(list)
        for p in active:
            pid = p.id if hasattr(p, "id") else p
            brackets[standings[pid].score].append(p)

        sorted_scores = sorted(brackets.keys(), reverse=True)

        pairings: list[Pairing] = []
        used: set[int] = set()
        all_paired: set[int] = set()
        dropped_down: int | None = None
        table = 1

        for score in sorted_scores:
            bracket = sorted(
                brackets[score],
                key=lambda p: (
                    -standings[p.id].opponent_win_percent,
                    -(p.seed or 0),
                )
            )

            if round_number == 1:
                import random
                random.shuffle(bracket)

            pool = []
            if dropped_down is not None:
                dd_player = next((p for p in bracket if p.id == dropped_down), None)
                if dd_player:
                    pool.append(dd_player)
                    dropped_down = None

            pool.extend(p for p in bracket if p.id not in used)

            paired = set()
            i = 0
            while i < len(pool):
                p1 = pool[i]
                pid1 = p1.id if hasattr(p1, "id") else p1
                if pid1 in paired:
                    i += 1
                    continue

                opponent = None
                for j in range(i + 1, len(pool)):
                    p2 = pool[j]
                    pid2 = p2.id if hasattr(p2, "id") else p2
                    if pid2 in paired:
                        continue
                    a, b = (pid1, pid2) if pid1 < pid2 else (pid2, pid1)
                    if (a, b) in existing:
                        continue
                    opponent = pid2
                    break

                if opponent is not None:
                    pairings.append(Pairing(
                        player1_id=pid1,
                        player2_id=opponent,
                        table_number=table,
                    ))
                    paired.add(pid1)
                    paired.add(opponent)
                    all_paired.add(pid1)
                    all_paired.add(opponent)
                    table += 1
                else:
                    player_obj = next(
                        (p for p in active if (p.id if hasattr(p, "id") else p) == pid1),
                        None
                    )
                    if player_obj:
                        dropped_down = pid1
                        used.add(pid1)

                i += 1

        unpaired = [p for p in active if (
            p.id if hasattr(p, "id") else p
        ) not in all_paired and (
            p.id if hasattr(p, "id") else p
        ) not in used]

        if dropped_down is not None:
            dd_p = next(
                (p for p in active if (p.id if hasattr(p, "id") else p) == dropped_down),
                None,
            )
            if dd_p:
                unpaired.append(dd_p)

        unpaired.sort(
            key=lambda p: (
                standings[p.id].score,
                p.id in bye_received,
                -(p.seed or 0),
            )
        )

        for p in unpaired:
            pid = p.id if hasattr(p, "id") else p
            pairings.append(Pairing(
                player1_id=pid,
                player2_id=None,
                table_number=table,
            ))
            table += 1

        return pairings
