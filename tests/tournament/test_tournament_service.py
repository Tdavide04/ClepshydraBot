import asyncio

# The test env vars (TEST_MODE, GUILD_ID_TEST, etc.) are set by
# tests/tournament/conftest.py, which pytest loads before this module:
# required because services/__init__.py eagerly imports TournamentService,
# which needs a populated config.config.
import pytest

import database.engine as db_engine
from core.results import ResultKind
from database import close_db, init_db
from database.models import MatchResult, TournamentStatus
from services.tournament_service import TournamentService


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Every test gets a temporary, isolated SQLite DB, so autoincrement ids
    (used to infer tournament_player.id in the tests) stay deterministic."""
    monkeypatch.setattr(db_engine, "DB_PATH", str(tmp_path / "tournament_service_test.db"))
    db_engine._engine = None
    db_engine._async_session_maker = None
    yield


def run_with_db(scenario):
    """Runs the whole scenario (init_db + logic + close_db) in a single event
    loop: aiosqlite binds connections to the loop that created them, so
    init/use/close can't be spread over several asyncio.run() calls."""

    async def _wrapper():
        await init_db()
        try:
            return await scenario()
        finally:
            await close_db()

    return asyncio.run(_wrapper())


class TestRegistration:
    def test_register_and_duplicate(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Test Cup")
            first = await service.register_player(t.id, discord_id=1, deck_name="Mono Red")
            assert first.ok is True
            duplicate = await service.register_player(t.id, discord_id=1)
            assert duplicate.ok is False
            assert "gia iscritto" in duplicate.message

        run_with_db(scenario)

    def test_registration_to_a_full_tournament_is_a_failed_result(self, isolated_db):
        """Regression (3.6.7): /iscriviti never looked at the outcome, so a registration refused
        because the tournament was full was announced publicly as confirmed. The refusal must be readable
        from a field, not only from the message text."""

        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Full Cup", max_players=1)
            first = await service.register_player(t.id, discord_id=1)
            second = await service.register_player(t.id, discord_id=2)
            assert first.ok is True
            assert second.ok is False
            assert "massimo" in second.message

        run_with_db(scenario)

    def test_rejoin_after_drop(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Rejoin Cup")
            await service.register_player(t.id, discord_id=1)
            await service.unregister_player(t.id, discord_id=1)
            rejoin = await service.register_player(t.id, discord_id=1, deck_name="Azorius Fliers")
            assert rejoin.ok is True

        run_with_db(scenario)

    def test_max_players_enforced_under_concurrent_registrations(self, isolated_db):
        """Two simultaneous /iscriviti for the last seat: the limit check and
        the insert were not atomic, both got through (reproduced: 3
        registrations with max 2)."""

        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Full Cup", max_players=2)
            await service.register_player(t.id, discord_id=1)

            results = await asyncio.gather(
                service.register_player(t.id, discord_id=2),
                service.register_player(t.id, discord_id=3),
            )

            assert sum(r.ok for r in results) == 1
            assert sum("massimo" in r.message for r in results if not r.ok) == 1
            assert len(await service.get_registered_players(t.id)) == 2

        run_with_db(scenario)

    def test_seed_is_unique_after_a_player_leaves(self, isolated_db):
        """The seed was count(active registrations) + 1: after a drop, the new
        registration got the same seed as an existing one."""

        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Seed Cup")
            await service.register_player(t.id, discord_id=1)
            await service.register_player(t.id, discord_id=2)
            await service.unregister_player(t.id, discord_id=1)

            await service.register_player(t.id, discord_id=3)

            seeds = [p.seed for p in await service.get_registered_players(t.id)]
            assert seeds == [2, 3]

        run_with_db(scenario)

    def test_unregister_twice_reports_not_registered(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Leave Cup")
            await service.register_player(t.id, discord_id=1)
            await service.unregister_player(t.id, discord_id=1)

            outcome = await service.unregister_player(t.id, discord_id=1)

            assert outcome.ok is False
            assert "Non sei iscritto" in outcome.message

        run_with_db(scenario)


class TestDeckSubmission:
    def test_submit_deck_updates_existing_registration(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Deck Cup")
            await service.register_player(t.id, discord_id=1)  # no deck
            outcome = await service.submit_deck(t.id, discord_id=1, deck_name="Mono Red")
            assert outcome.ok is True

            players = await service.get_registered_players(t.id)
            assert players[0].deck_name == "Mono Red"

        run_with_db(scenario)

    def test_submit_deck_can_be_resent_before_start(self, isolated_db):
        """A player can fix the submitted deck several times while the
        tournament is in registration: the latest valid submission wins."""

        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Deck Cup")
            await service.register_player(t.id, discord_id=1)
            await service.submit_deck(t.id, discord_id=1, deck_name="Wrong Draft")
            await service.submit_deck(t.id, discord_id=1, deck_name="Final Version")

            players = await service.get_registered_players(t.id)
            assert players[0].deck_name == "Final Version"

        run_with_db(scenario)

    def test_submit_deck_to_an_unknown_tournament_is_a_failed_result(self, isolated_db):
        """Regression (3.6.7): /invia_deck matched only "Non sei iscritto"/"non accetta piu", so the
        service's "Torneo non trovato." was treated as a recorded deck."""

        async def scenario():
            service = TournamentService()
            outcome = await service.submit_deck(999, discord_id=1, deck_name="Mono Red")
            assert outcome.ok is False
            assert "non trovato" in outcome.message

        run_with_db(scenario)

    def test_submit_deck_requires_existing_registration(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Deck Cup")
            outcome = await service.submit_deck(t.id, discord_id=999, deck_name="Mono Red")
            assert outcome.ok is False
            assert "Non sei iscritto" in outcome.message

        run_with_db(scenario)

    def test_submit_deck_blocked_after_tournament_started(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Deck Cup")
            await service.register_player(t.id, discord_id=1, deck_name="Mono Red")
            await service.register_player(t.id, discord_id=2, deck_name="Mono Blue")
            await service.start_tournament(t.id)

            outcome = await service.submit_deck(t.id, discord_id=1, deck_name="New Deck")
            assert outcome.ok is False
            assert "non accetta piu" in outcome.message

        run_with_db(scenario)


class TestTournamentFlow:
    async def _start_with_players(self, service, count):
        t = await service.create_tournament("Swiss Cup")
        for i in range(count):
            await service.register_player(t.id, discord_id=1000 + i, deck_name=f"Deck {i}")
        outcome = await service.start_tournament(t.id)
        return t, outcome

    def test_start_requires_two_players(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Solo Cup")
            await service.register_player(t.id, discord_id=1)
            outcome = await service.start_tournament(t.id)
            assert outcome.ok is False
            assert "almeno 2" in outcome.message

        run_with_db(scenario)

    def test_start_blocked_if_deck_missing(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Swiss Cup")
            await service.register_player(t.id, discord_id=1, deck_name="Mono Red")
            await service.register_player(t.id, discord_id=2)  # no deck submitted
            outcome = await service.start_tournament(t.id)
            assert outcome.ok is False
            assert "non hanno ancora inviato un mazzo" in outcome.message

            tournament = await service.get_tournament(t.id)
            assert tournament.status == TournamentStatus.REGISTRATION

        run_with_db(scenario)

    def test_start_generates_round_one(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t, outcome = await self._start_with_players(service, 4)
            assert outcome.ok is True
            tournament = await service.get_tournament(t.id)
            assert tournament.status == TournamentStatus.ACTIVE
            matches = await service.get_matches(t.id)
            assert len(matches) == 2

        run_with_db(scenario)

    def test_bye_awarded_with_odd_players(self, isolated_db):
        async def scenario():
            service = TournamentService()
            _, outcome = await self._start_with_players(service, 3)
            assert outcome.ok is True
            assert "bye" in outcome.message.lower()

        run_with_db(scenario)

    def test_submit_result_flow(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t, _ = await self._start_with_players(service, 2)
            match = (await service.get_matches(t.id))[0]

            outcome = await service.submit_result(match.id, match.player1_id, "win")
            assert outcome.ok is True

            repeat = await service.submit_result(match.id, match.player1_id, "win")
            assert repeat.ok is False
            assert "/correggi_risultato" in repeat.message

        run_with_db(scenario)

    def test_generate_next_round_blocked_by_pending_results(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t, _ = await self._start_with_players(service, 4)
            outcome = await service.generate_next_round(t.id)
            assert outcome.ok is False
            assert outcome.kind is ResultKind.PENDING_RESULTS

        run_with_db(scenario)

    def test_generate_next_round_avoids_rematch(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t, _ = await self._start_with_players(service, 4)
            round1 = await service.get_matches(t.id)
            for m in round1:
                await service.submit_result(m.id, m.player1_id, "win")

            outcome = await service.generate_next_round(t.id)
            assert outcome.ok is True
            assert outcome.kind is None

            round2 = [m for m in await service.get_matches(t.id) if m.round_number == 2]
            round1_pairs = {frozenset((m.player1_id, m.player2_id)) for m in round1}
            round2_pairs = {frozenset((m.player1_id, m.player2_id)) for m in round2}
            assert round1_pairs.isdisjoint(round2_pairs)

        run_with_db(scenario)

    def test_tournament_completes_and_updates_rating(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Rating Cup", max_players=2)
            await service.register_player(t.id, discord_id=1, deck_name="Mono Red")
            await service.register_player(t.id, discord_id=2, deck_name="Mono Blue")
            await service.start_tournament(t.id)

            match = (await service.get_matches(t.id))[0]
            await service.submit_result(match.id, match.player1_id, "win")

            outcome = await service.generate_next_round(t.id)
            assert outcome.ok is True
            assert outcome.kind is ResultKind.TOURNAMENT_COMPLETED

            tournament = await service.get_tournament(t.id)
            assert tournament.status == TournamentStatus.COMPLETED

            leaderboard = await service.get_leaderboard()
            assert len(leaderboard) == 2
            ratings = {entry["discord_id"]: entry["rating"] for entry in leaderboard}
            assert ratings[1] != ratings[2]

        run_with_db(scenario)

    def test_force_drop_awards_win_to_opponent(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t, _ = await self._start_with_players(service, 2)
            match = (await service.get_matches(t.id))[0]

            # First registration on an isolated, empty DB -> tournament_player.id == 1
            await service.force_drop_player(t.id, discord_id=1000)

            updated = next(m for m in await service.get_matches(t.id) if m.id == match.id)
            assert updated.result == MatchResult.WIN
            assert updated.winner_id == 2

        run_with_db(scenario)

    def test_standings_after_active_drop_keep_the_dropped_player(self, isolated_db):
        """Regression: after a /drop_giocatore on an active tournament,
        /classifica raised KeyError (the dropped player's matches stay, the
        player doesn't)."""

        async def scenario():
            service = TournamentService()
            t, _ = await self._start_with_players(service, 4)
            for m in await service.get_matches(t.id):
                await service.submit_result(m.id, m.player1_id, "win", 2, 0)

            # Round 1 is random: drop the winner of a match, whoever it is.
            winner = (await service.get_matches(t.id))[0].player1
            await service.force_drop_player(t.id, discord_id=winner.user.discord_id)
            entries = await service.get_standings(t.id)

            assert len(entries) == 4
            dropped = [e for e in entries if e.dropped]
            assert [e.player_id for e in dropped] == [winner.id]
            assert dropped[0].points == 3

        run_with_db(scenario)

    def test_player_who_left_during_registration_is_not_in_standings(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Left Cup")
            await service.register_player(t.id, discord_id=1)
            await service.register_player(t.id, discord_id=2)
            await service.unregister_player(t.id, discord_id=1)

            entries = await service.get_standings(t.id)

            assert len(entries) == 1

        run_with_db(scenario)

    def test_ratings_count_matches_against_a_dropped_player(self, isolated_db):
        """_update_ratings() skipped matches against a player who was later
        dropped: the winner's rating didn't change."""

        async def scenario():
            service = TournamentService()
            t, _ = await self._start_with_players(service, 2)
            match = (await service.get_matches(t.id))[0]
            winner_id = match.player1.user.discord_id
            loser_id = match.player2.user.discord_id
            await service.submit_result(match.id, match.player1_id, "win", 2, 0)
            await service.force_drop_player(t.id, discord_id=loser_id)

            await service.generate_next_round(t.id)

            board = {e["discord_id"]: e for e in await service.get_leaderboard()}
            assert board[winner_id]["rating"] > 1500
            assert board[loser_id]["rating"] < 1500

        run_with_db(scenario)

    def test_force_drop_during_registration_unblocks_start(self, isolated_db):
        """A registered player who never submits a deck blocked
        /avvia_torneo, and staff couldn't remove them: force_drop_player()
        only accepted ACTIVE tournaments."""

        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("AFK Cup")
            for discord_id in (1, 2, 3):
                await service.register_player(t.id, discord_id=discord_id)
            await service.submit_deck(t.id, 1, "Deck 1")
            await service.submit_deck(t.id, 2, "Deck 2")
            assert (await service.start_tournament(t.id)).ok is False

            dropped = await service.force_drop_player(t.id, discord_id=3)

            assert dropped.ok is True
            assert [p.user.discord_id for p in await service.get_registered_players(t.id)] == [1, 2]
            assert (await service.start_tournament(t.id)).ok is True

        run_with_db(scenario)

    def test_force_drop_rejected_on_completed_tournament(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t, _ = await self._start_with_players(service, 2)
            assert (await service.force_conclude_tournament(t.id)).ok is True

            outcome = await service.force_drop_player(t.id, discord_id=1000)

            assert outcome.ok is False
            assert "non e attivo" in outcome.message

        run_with_db(scenario)


class TestStandings:
    def test_standings_reflect_results(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Standings Cup")
            await service.register_player(t.id, discord_id=1, deck_name="Boros Aggro")
            await service.register_player(t.id, discord_id=2, deck_name="Dimir Control")
            await service.start_tournament(t.id)

            match = (await service.get_matches(t.id))[0]
            await service.submit_result(match.id, match.player1_id, "win")

            standings = await service.get_standings(t.id)
            leader = next(e for e in standings if e.player_id == match.player1_id)
            assert leader.points == 3.0
            assert leader.rank == 1

        run_with_db(scenario)


class TestCorrectResult:
    """/correggi_risultato: staff overwrites (or enters) a match result -
    before, a wrong result could only be fixed by hand in the DB."""

    async def _start(self, service, count):
        t = await service.create_tournament("Fix Cup")
        for i in range(count):
            await service.register_player(t.id, discord_id=1000 + i, deck_name=f"Deck {i}")
        await service.start_tournament(t.id)
        return t

    def test_overwrites_a_wrong_result(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await self._start(service, 2)
            match = (await service.get_matches(t.id))[0]
            await service.submit_result(match.id, match.player1_id, "win", 2, 0)
            loser = match.player2.user.discord_id

            outcome = await service.correct_result(t.id, None, match.table_number, loser, 2, 1)

            assert outcome.ok is True
            updated = (await service.get_matches(t.id))[0]
            assert updated.winner_id == match.player2_id
            assert (updated.p1_game_wins, updated.p2_game_wins) == (1, 2)
            standings = {e.player_id: e.points for e in await service.get_standings(t.id)}
            assert standings[match.player2_id] == 3
            assert standings[match.player1_id] == 0

        run_with_db(scenario)

    def test_can_enter_a_missing_result_and_a_draw(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await self._start(service, 2)
            match = (await service.get_matches(t.id))[0]

            outcome = await service.correct_result(t.id, None, match.table_number, None, 1, 1)

            assert outcome.ok is True
            updated = (await service.get_matches(t.id))[0]
            assert updated.result == MatchResult.DRAW
            assert updated.winner_id is None

        run_with_db(scenario)

    def test_rejects_a_player_not_at_that_table(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await self._start(service, 2)
            match = (await service.get_matches(t.id))[0]

            outcome = await service.correct_result(t.id, None, match.table_number, 999999, 2, 0)

            assert outcome.ok is False

        run_with_db(scenario)

    def test_rejects_unknown_table_and_bye(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await self._start(service, 3)
            bye = next(m for m in await service.get_matches(t.id) if m.player2_id is None)

            missing = await service.correct_result(t.id, None, 99, None, 1, 1)
            on_bye = await service.correct_result(t.id, None, bye.table_number, None, 1, 1)

            assert missing.ok is False
            assert on_bye.ok is False

        run_with_db(scenario)

    def test_rejected_on_a_completed_tournament(self, isolated_db):
        """Once the tournament is concluded the rating has already been
        applied: a correction would make it inconsistent."""

        async def scenario():
            service = TournamentService()
            t = await self._start(service, 2)
            match = (await service.get_matches(t.id))[0]
            await service.submit_result(match.id, match.player1_id, "win", 2, 0)
            await service.generate_next_round(t.id)

            outcome = await service.correct_result(
                t.id, 1, match.table_number, match.player2.user.discord_id, 2, 0
            )

            assert outcome.ok is False

        run_with_db(scenario)

    def test_correcting_a_past_round_warns_pairings_are_unchanged(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await self._start(service, 4)
            round1 = await service.get_matches(t.id)
            for m in round1:
                await service.submit_result(m.id, m.player1_id, "win", 2, 0)
            await service.generate_next_round(t.id)
            m = round1[0]

            outcome = await service.correct_result(t.id, 1, m.table_number, m.player2.user.discord_id, 2, 0)

            assert outcome.ok is True
            assert "abbinamenti" in outcome.message

        run_with_db(scenario)
