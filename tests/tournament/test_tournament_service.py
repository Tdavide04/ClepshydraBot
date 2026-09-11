import asyncio

# Le variabili d'ambiente di test (TEST_MODE, GUILD_ID_TEST, ecc.) sono
# impostate da tests/tournament/conftest.py, caricato da pytest prima di
# questo modulo: necessario perche' services/__init__.py importa eagerly
# TournamentService, che richiede config.config popolato.
import pytest

import database.engine as db_engine
from database import init_db, close_db
from database.models import MatchResult, TournamentStatus
from services.tournament_service import TournamentService


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Ogni test riceve un DB SQLite temporaneo e isolato, cosi' gli id
    autoincrementali (usati per dedurre i tournament_player.id nei test)
    restano deterministici."""
    monkeypatch.setattr(db_engine, "DB_PATH", str(tmp_path / "tournament_service_test.db"))
    db_engine._engine = None
    db_engine._async_session_maker = None
    yield


def run_with_db(scenario):
    """Esegue l'intero scenario (init_db + logica + close_db) in un unico
    event loop: aiosqlite lega le connessioni al loop che le ha create,
    quindi init/uso/chiusura non possono essere sparsi su piu' asyncio.run()."""
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
            msg1 = await service.register_player(t.id, discord_id=1, deck_name="Mono Red")
            assert "Iscrizione confermata" in msg1
            msg2 = await service.register_player(t.id, discord_id=1)
            assert "gia iscritto" in msg2
        run_with_db(scenario)

    def test_max_players_enforced(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Piccolo", max_players=1)
            await service.register_player(t.id, discord_id=1)
            msg = await service.register_player(t.id, discord_id=2)
            assert "massimo" in msg
        run_with_db(scenario)

    def test_rejoin_after_drop(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Rejoin Cup")
            await service.register_player(t.id, discord_id=1)
            await service.unregister_player(t.id, discord_id=1)
            msg = await service.register_player(t.id, discord_id=1, deck_name="Azorius Fliers")
            assert "confermata" in msg
        run_with_db(scenario)


class TestDeckSubmission:

    def test_submit_deck_updates_existing_registration(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Deck Cup")
            await service.register_player(t.id, discord_id=1)  # senza mazzo
            msg = await service.submit_deck(t.id, discord_id=1, deck_name="Mono Red")
            assert "Mono Red" in msg

            players = await service.get_registered_players(t.id)
            assert players[0].deck_name == "Mono Red"
        run_with_db(scenario)

    def test_submit_deck_can_be_resent_before_start(self, isolated_db):
        """Un giocatore puo' correggere il mazzo inviato piu' volte finche' il
        torneo resta in registrazione: l'ultimo invio valido sovrascrive."""
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Deck Cup")
            await service.register_player(t.id, discord_id=1)
            await service.submit_deck(t.id, discord_id=1, deck_name="Bozza Sbagliata")
            await service.submit_deck(t.id, discord_id=1, deck_name="Versione Finale")

            players = await service.get_registered_players(t.id)
            assert players[0].deck_name == "Versione Finale"
        run_with_db(scenario)

    def test_submit_deck_requires_existing_registration(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Deck Cup")
            msg = await service.submit_deck(t.id, discord_id=999, deck_name="Mono Red")
            assert "Non sei iscritto" in msg
        run_with_db(scenario)

    def test_submit_deck_blocked_after_tournament_started(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Deck Cup")
            await service.register_player(t.id, discord_id=1, deck_name="Mono Red")
            await service.register_player(t.id, discord_id=2, deck_name="Mono Blue")
            await service.start_tournament(t.id)

            msg = await service.submit_deck(t.id, discord_id=1, deck_name="Nuovo Mazzo")
            assert "non accetta piu" in msg
        run_with_db(scenario)


class TestTournamentFlow:

    async def _start_with_players(self, service, count):
        t = await service.create_tournament("Swiss Cup")
        for i in range(count):
            await service.register_player(t.id, discord_id=1000 + i, deck_name=f"Deck {i}")
        msg = await service.start_tournament(t.id)
        return t, msg

    def test_start_requires_two_players(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Solo Cup")
            await service.register_player(t.id, discord_id=1)
            msg = await service.start_tournament(t.id)
            assert "almeno 2" in msg
        run_with_db(scenario)

    def test_start_blocked_if_deck_missing(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t = await service.create_tournament("Swiss Cup")
            await service.register_player(t.id, discord_id=1, deck_name="Mono Red")
            await service.register_player(t.id, discord_id=2)  # nessun mazzo inviato
            msg = await service.start_tournament(t.id)
            assert "non hanno ancora inviato un mazzo" in msg

            tournament = await service.get_tournament(t.id)
            assert tournament.status == TournamentStatus.REGISTRATION
        run_with_db(scenario)

    def test_start_generates_round_one(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t, msg = await self._start_with_players(service, 4)
            assert "iniziato" in msg
            tournament = await service.get_tournament(t.id)
            assert tournament.status == TournamentStatus.ACTIVE
            matches = await service.get_matches(t.id)
            assert len(matches) == 2
        run_with_db(scenario)

    def test_bye_awarded_with_odd_players(self, isolated_db):
        async def scenario():
            service = TournamentService()
            _, msg = await self._start_with_players(service, 3)
            assert "bye" in msg.lower()
        run_with_db(scenario)

    def test_submit_result_flow(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t, _ = await self._start_with_players(service, 2)
            match = (await service.get_matches(t.id))[0]

            msg = await service.submit_result(match.id, match.player1_id, "win")
            assert "registrato" in msg.lower()

            repeat = await service.submit_result(match.id, match.player1_id, "win")
            assert "gia inserito" in repeat.lower()
        run_with_db(scenario)

    def test_generate_next_round_blocked_by_pending_results(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t, _ = await self._start_with_players(service, 4)
            msg = await service.generate_next_round(t.id)
            assert "senza risultato" in msg
        run_with_db(scenario)

    def test_generate_next_round_avoids_rematch(self, isolated_db):
        async def scenario():
            service = TournamentService()
            t, _ = await self._start_with_players(service, 4)
            round1 = await service.get_matches(t.id)
            for m in round1:
                await service.submit_result(m.id, m.player1_id, "win")

            msg = await service.generate_next_round(t.id)
            assert "Round 2 generato" in msg

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

            msg = await service.generate_next_round(t.id)
            assert "completato" in msg.lower()

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

            # Primo iscritto su un DB isolato e vuoto -> tournament_player.id == 1
            await service.force_drop_player(t.id, discord_id=1000)

            updated = next(m for m in await service.get_matches(t.id) if m.id == match.id)
            assert updated.result == MatchResult.WIN
            assert updated.winner_id == 2
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
