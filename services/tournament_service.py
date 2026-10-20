import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import select

from database import get_session
from database.models import (
    Tournament, TournamentPlayer, Match, User,
    TournamentStatus, MatchResult,
)
from repositories.tournament_repository import (
    TournamentRepository,
    TournamentPlayerRepository,
    MatchRepository,
)
from repositories.user_repository import UserRepository
from services.pairing_engine import PairingEngine
from services.results import ServiceResult
from services.standings import StandingsCalculator, StandingsEntry
from services.rating import Rating, rate_1vs1, rate_draw
from config.config import GUILD_ID


class TournamentService:

    def __init__(self, bot=None):
        self.bot = bot
        # Serializes register_player(): the max_players check and the insert
        # are separate queries with an await in between - two simultaneous
        # /iscriviti for the last seat both got through. Per-instance lock,
        # not module-level (asyncio.Lock binds to the event loop on first
        # contention, and tests use one loop per scenario): enough because the
        # bot creates a single TournamentService (cogs/tournament_system/cog.py).
        self._registration_lock = asyncio.Lock()

    @asynccontextmanager
    async def _repos(self):
        """Opens a DB session and its repositories; always closes them when the
        block exits, on a normal return as well as on an exception."""
        session = get_session()
        try:
            yield (
                session,
                TournamentRepository(session),
                TournamentPlayerRepository(session),
                MatchRepository(session),
                UserRepository(session),
            )
        finally:
            await session.close()

    def _resolve_name(self, tp: TournamentPlayer) -> str:
        if tp.user and self.bot:
            guild = self.bot.get_guild(GUILD_ID)
            if guild:
                member = guild.get_member(tp.user.discord_id)
                if member:
                    return member.display_name
        return f"Giocatore #{tp.id}"

    async def create_tournament(
        self,
        name: str,
        format: str = "Artisan",
        max_players: int | None = None,
    ) -> Tournament:
        async with self._repos() as (session, repo, _, _, _):
            tournament = Tournament(
                name=name,
                format=format,
                max_players=max_players,
            )
            result = await repo.add(tournament)
            return result

    async def list_tournaments(self) -> list[Tournament]:
        async with self._repos() as (session, repo, _, _, _):
            return await repo.list_all()

    async def list_tournaments_with_counts(self) -> list[tuple[Tournament, int]]:
        async with self._repos() as (session, trepo, tprepo, _, _):
            tournaments = await trepo.list_all()
            tournaments.sort(key=lambda t: t.created_at or datetime.min, reverse=True)
            result = []
            for t in tournaments:
                count = await tprepo.count_in_tournament(t.id)
                result.append((t, count))
            return result

    async def register_player(
        self, tournament_id: int, discord_id: int, deck_name: str | None = None
    ) -> str:
        async with self._registration_lock:
            return await self._register_player(tournament_id, discord_id, deck_name)

    async def _register_player(
        self, tournament_id: int, discord_id: int, deck_name: str | None
    ) -> str:
        async with self._repos() as (session, trepo, tprepo, _, urepo):
            tournament = await trepo.get_by_id(tournament_id)
            if tournament is None:
                return "Torneo non trovato."
            if tournament.status != TournamentStatus.REGISTRATION:
                return "Il torneo non accetta iscrizioni."

            if tournament.max_players:
                count = await tprepo.count_in_tournament(tournament_id)
                if count >= tournament.max_players:
                    return "Il torneo ha raggiunto il massimo dei partecipanti."

            user = await urepo.get_or_create(discord_id)
            existing = await tprepo.get_by_tournament_and_user(
                tournament_id, user.id
            )
            if existing is not None:
                if not existing.dropped:
                    return "Sei gia iscritto a questo torneo."
                existing.dropped = False
                existing.deck_name = deck_name
                session.add(existing)
                await session.commit()
                deck_info = f" con **{deck_name}**" if deck_name else ""
                return f"Iscrizione confermata al torneo **{tournament.name}** (seed #{existing.seed}){deck_info}."

            # Not count + 1: the count excludes dropped players, so after a
            # drop the new seed collided with one already assigned.
            seed = await tprepo.max_seed(tournament_id) + 1
            tp = TournamentPlayer(
                tournament_id=tournament_id,
                user_id=user.id,
                seed=seed,
                deck_name=deck_name,
            )
            await tprepo.add(tp)
            deck_info = f" con **{deck_name}**" if deck_name else ""
            return f"Iscrizione confermata al torneo **{tournament.name}** (seed #{seed}){deck_info}."

    async def submit_deck(
        self, tournament_id: int, discord_id: int, deck_name: str
    ) -> str:
        """Records/updates the deck of an already registered player. Unlike
        register_player(), it doesn't create a registration: the
        TournamentPlayer must already exist (and not be dropped). Can be called
        repeatedly while the tournament is in REGISTRATION: the latest valid
        submission overwrites the previous one."""
        async with self._repos() as (session, trepo, tprepo, _, urepo):
            tournament = await trepo.get_by_id(tournament_id)
            if tournament is None:
                return "Torneo non trovato."
            if tournament.status != TournamentStatus.REGISTRATION:
                return "Il torneo non accetta piu' invii di mazzo."

            user = await urepo.get_by_discord_id(discord_id)
            tp = (
                await tprepo.get_by_tournament_and_user(tournament_id, user.id)
                if user else None
            )
            if tp is None or tp.dropped:
                return "Non sei iscritto a questo torneo: usa /iscriviti prima."

            tp.deck_name = deck_name
            session.add(tp)
            await session.commit()
            return f"Mazzo **{deck_name}** registrato per il torneo **{tournament.name}**."

    async def start_tournament(self, tournament_id: int) -> str:
        async with self._repos() as (session, trepo, tprepo, mrepo, _):
            tournament = await trepo.get_with_players(tournament_id)
            if tournament is None:
                return "Torneo non trovato."
            if tournament.status != TournamentStatus.REGISTRATION:
                return "Il torneo e gia iniziato o concluso."

            players = await tprepo.get_by_tournament(tournament_id)
            if len(players) < 2:
                return "Servono almeno 2 giocatori per iniziare."

            missing_deck = [p for p in players if p.deck_name is None]
            if missing_deck:
                names = ", ".join(self._resolve_name(p) for p in missing_deck)
                return (
                    f"Impossibile avviare: {len(missing_deck)} giocatore/i non hanno "
                    f"ancora inviato un mazzo con /invia_deck ({names})."
                )

            round_count = PairingEngine.calculate_rounds(len(players))
            tournament.round_count = round_count
            tournament.status = TournamentStatus.ACTIVE
            tournament.started_at = datetime.now()
            session.add(tournament)
            await session.commit()

            pairings = PairingEngine.generate_round(players, [], 1)
            for i, pairing in enumerate(pairings):
                match = Match(
                    tournament_id=tournament_id,
                    round_number=1,
                    player1_id=pairing.player1_id,
                    player2_id=pairing.player2_id,
                    table_number=pairing.table_number,
                )
                session.add(match)
            await session.commit()

            bye_count = sum(
                1 for p in pairings if p.player2_id is None
            )
            msg = (
                f"Torneo **{tournament.name}** iniziato! "
                f"{len(players)} giocatori, {round_count} round previsti."
            )
            if bye_count:
                msg += f"\n{bye_count} giocatore/i prendono il bye al primo turno."
            return msg

    async def get_latest_tournament(self) -> Tournament | None:
        async with self._repos() as (session, trepo, _, _, _):
            tournaments = await trepo.list_all()
            if not tournaments:
                return None
            return max(tournaments, key=lambda t: t.id)

    async def find_tournament(self, identifier: str) -> Tournament | None:
        async with self._repos() as (session, trepo, _, _, _):
            if identifier.isdigit():
                return await trepo.get_by_id(int(identifier))
            return await trepo.find_by_name(identifier)

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        async with self._repos() as (session, trepo, _, _, _):
            return await trepo.get_by_id(tournament_id)

    async def is_player_registered(
        self, tournament_id: int, discord_id: int
    ) -> bool:
        async with self._repos() as (session, _, tprepo, _, urepo):
            user = await urepo.get_by_discord_id(discord_id)
            if user is None:
                return False
            existing = await tprepo.get_by_tournament_and_user(
                tournament_id, user.id
            )
            return existing is not None and not existing.dropped

    async def get_registered_players(
        self, tournament_id: int
    ) -> list[TournamentPlayer]:
        async with self._repos() as (session, _, tprepo, _, _):
            return await tprepo.get_by_tournament(tournament_id)

    async def unregister_player(
        self, tournament_id: int, discord_id: int
    ) -> str:
        async with self._repos() as (session, trepo, tprepo, _, urepo):
            tournament = await trepo.get_by_id(tournament_id)
            if tournament is None:
                return "Torneo non trovato."
            if tournament.status != TournamentStatus.REGISTRATION:
                return "Non puoi uscire da un torneo già iniziato o completato."

            user = await urepo.get_by_discord_id(discord_id)
            if user is None:
                return "Non sei iscritto a questo torneo."

            tp = await tprepo.get_by_tournament_and_user(tournament_id, user.id)
            if tp is None or tp.dropped:
                return "Non sei iscritto a questo torneo."

            tp.dropped = True
            session.add(tp)
            await session.commit()
            return f"Sei uscito dal torneo **{tournament.name}**."

    async def force_drop_player(
        self, tournament_id: int, discord_id: int
    ) -> str:
        """Removal decided by staff. Also valid in REGISTRATION: a registered
        player who never submits a deck blocks start_tournament(), and only
        the player themselves can call unregister_player() - without this case
        staff had no way to unblock the start."""
        async with self._repos() as (session, trepo, tprepo, mrepo, urepo):
            tournament = await trepo.get_by_id(tournament_id)
            if tournament is None:
                return "Torneo non trovato."
            if tournament.status not in (TournamentStatus.ACTIVE, TournamentStatus.REGISTRATION):
                return "Il torneo non e attivo ne in fase di iscrizioni."

            user = await urepo.get_by_discord_id(discord_id)
            if user is None:
                return "Giocatore non trovato."

            tp = await tprepo.get_by_tournament_and_user(tournament_id, user.id)
            if tp is None or tp.dropped:
                return "Giocatore non iscritto o gia rimosso."

            if tournament.status == TournamentStatus.REGISTRATION:
                tp.dropped = True
                session.add(tp)
                await session.commit()
                return (
                    f"Giocatore **{self._resolve_name(tp)}** rimosso dalle iscrizioni "
                    f"del torneo **{tournament.name}**."
                )

            current_round = await mrepo.get_current_round(tournament_id)
            matches = await mrepo.get_by_tournament(tournament_id)

            pending = [
                m for m in matches
                if m.round_number == current_round
                and m.result is None
                and (m.player1_id == tp.id or m.player2_id == tp.id)
            ]

            for match in pending:
                if match.player2_id is None:
                    continue
                opponent_id = (
                    match.player1_id
                    if match.player2_id == tp.id
                    else match.player2_id
                )
                match.winner_id = opponent_id
                match.result = MatchResult.WIN
                session.add(match)

            tp.dropped = True
            session.add(tp)
            await session.commit()

            player_name = self._resolve_name(tp)
            return (
                f"Giocatore **{player_name}** rimosso dal torneo "
                f"**{tournament.name}**."
            )

    async def force_conclude_tournament(self, tournament_id: int) -> str:
        async with self._repos() as (session, trepo, _, _, _):
            tournament = await trepo.get_by_id(tournament_id)
            if tournament is None:
                return "Torneo non trovato."
            if tournament.status != TournamentStatus.ACTIVE:
                return "Il torneo non e attivo."

            tournament.status = TournamentStatus.COMPLETED
            tournament.ended_at = datetime.now()
            session.add(tournament)
            await session.commit()

            await self._update_ratings(tournament_id)

            return f"Torneo **{tournament.name}** concluso forzatamente."

    async def find_pending_match_for_user(
        self, tournament_id: int, discord_id: int
    ) -> Match | None:
        async with self._repos() as (session, _, tprepo, mrepo, urepo):
            user = await urepo.get_by_discord_id(discord_id)
            if user is None:
                return None

            tp = await tprepo.get_by_tournament_and_user(tournament_id, user.id)
            if tp is None or tp.dropped:
                return None

            current_round = await mrepo.get_current_round(tournament_id)
            if current_round == 0:
                return None

            matches = await mrepo.get_by_tournament(tournament_id)
            for m in matches:
                if (
                    m.round_number == current_round
                    and m.result is None
                    and (m.player1_id == tp.id or m.player2_id == tp.id)
                ):
                    return m
            return None

    async def submit_result(
        self,
        match_id: int,
        winner_tp_id: int | None,
        result: str | None,
        p1_game_wins: int | None = None,
        p2_game_wins: int | None = None,
    ) -> ServiceResult:
        async with self._repos() as (session, _, _, mrepo, _):
            match = await mrepo.get_by_id(match_id)
            if match is None:
                return ServiceResult(False, "Partita non trovata.")
            if match.result is not None:
                return ServiceResult(
                    False,
                    "Risultato già inserito per questa partita. Se è sbagliato, chiedi allo "
                    "staff di correggerlo con /correggi_risultato.",
                )
            if match.player2_id is None:
                return ServiceResult(False, "Questa è una partita di bye.")

            if result is not None:
                try:
                    match.result = MatchResult(result)
                except ValueError:
                    return ServiceResult(False, f"Risultato non valido: {result}")
                if winner_tp_id is not None:
                    if winner_tp_id not in (match.player1_id, match.player2_id):
                        return ServiceResult(False, "Il vincitore non è uno dei giocatori della partita.")
                    match.winner_id = winner_tp_id
            elif winner_tp_id is not None:
                if winner_tp_id not in (match.player1_id, match.player2_id):
                    return ServiceResult(False, "Il vincitore non è uno dei giocatori della partita.")
                match.winner_id = winner_tp_id
                match.result = MatchResult.WIN

            match.p1_game_wins = p1_game_wins
            match.p2_game_wins = p2_game_wins

            session.add(match)
            await session.commit()
            return ServiceResult(True, "Risultato registrato!")

    def _describe_result(self, match: Match) -> str:
        if match.result is None:
            return "nessun risultato"
        if match.result == MatchResult.DRAW or match.winner_id is None:
            return "pareggio"
        winner = match.player1 if match.winner_id == match.player1_id else match.player2
        description = f"vince {self._resolve_name(winner)}"
        if match.p1_game_wins is not None and match.p2_game_wins is not None:
            games = sorted((match.p1_game_wins, match.p2_game_wins), reverse=True)
            description += f" {games[0]}-{games[1]}"
        return description

    async def correct_result(
        self,
        tournament_id: int,
        round_number: int | None,
        table_number: int,
        winner_discord_id: int | None,
        winner_games: int,
        loser_games: int,
    ) -> ServiceResult:
        """Staff correction (/correggi_risultato): overwrites a match result, or
        enters it if missing (absent player). Before this, a wrong result -
        the first of the two players to submit decides, with no confirmation -
        could only be fixed by hand in the DB.

        winner_discord_id None = draw. round_number None = current round.
        ACTIVE tournaments only: once concluded, Glicko-2 ratings have already
        been applied and a correction would make them inconsistent. Correcting
        a past round is allowed: standings recompute on their own, pairings
        already generated stay as they are."""
        async with self._repos() as (session, trepo, _, mrepo, _):
            tournament = await trepo.get_by_id(tournament_id)
            if tournament is None:
                return ServiceResult(False, "Torneo non trovato.")
            if tournament.status != TournamentStatus.ACTIVE:
                return ServiceResult(
                    False,
                    "Si possono correggere solo i risultati di un torneo in corso: a torneo "
                    "concluso il rating è già stato calcolato.",
                )

            current_round = await mrepo.get_current_round(tournament_id)
            target_round = round_number or current_round
            matches = await mrepo.get_by_tournament_and_round(tournament_id, target_round)
            match = next((m for m in matches if m.table_number == table_number), None)
            if match is None:
                return ServiceResult(False, f"Nessuna partita al tavolo {table_number} del round {target_round}.")
            if match.player2_id is None:
                return ServiceResult(False, "Quella è una partita di bye: non ha un risultato da correggere.")

            before = self._describe_result(match)

            if winner_discord_id is None:
                match.result = MatchResult.DRAW
                match.winner_id = None
                match.p1_game_wins = None
                match.p2_game_wins = None
            else:
                winner = next(
                    (tp for tp in (match.player1, match.player2)
                     if tp is not None and tp.user is not None and tp.user.discord_id == winner_discord_id),
                    None,
                )
                if winner is None:
                    return ServiceResult(False, "Il giocatore indicato non gioca a quel tavolo.")
                match.result = MatchResult.WIN
                match.winner_id = winner.id
                if winner.id == match.player1_id:
                    match.p1_game_wins, match.p2_game_wins = winner_games, loser_games
                else:
                    match.p1_game_wins, match.p2_game_wins = loser_games, winner_games

            session.add(match)
            await session.commit()

            message = (
                f"Round {target_round}, tavolo {table_number}: {before} → {self._describe_result(match)}."
            )
            if target_round < current_round:
                message += (
                    "\nLa classifica è aggiornata; gli abbinamenti dei round successivi, già "
                    "generati, restano invariati."
                )
            return ServiceResult(True, message)

    async def _update_ratings(self, tournament_id: int):
        async with self._repos() as (session, _, tprepo, mrepo, urepo):
            tournament = await session.get(Tournament, tournament_id)
            if tournament is None:
                return

            # Dropped players included: matches already played against someone
            # who dropped count toward both players' ratings.
            players = await tprepo.get_by_tournament(tournament_id, include_dropped=True)
            matches = await mrepo.get_by_tournament(tournament_id)

            user_ids = {tp.user_id for tp in players if tp.user_id}
            user_map: dict[int, User] = {}
            if user_ids:
                result = await session.execute(select(User).where(User.id.in_(user_ids)))
                user_map = {u.id: u for u in result.scalars()}

            for m in matches:
                if m.player2_id is None or m.result is None:
                    continue
                if m.winner_id is None and m.result != MatchResult.DRAW:
                    continue

                tp1 = next((tp for tp in players if tp.id == m.player1_id), None)
                tp2 = next((tp for tp in players if tp.id == m.player2_id), None)
                if not tp1 or not tp2 or not tp1.user_id or not tp2.user_id:
                    continue

                u1 = user_map.get(tp1.user_id)
                u2 = user_map.get(tp2.user_id)
                if not u1 or not u2:
                    continue

                r1 = Rating(u1.rating, u1.rating_deviation, u1.rating_volatility, u1.rating_matches)
                r2 = Rating(u2.rating, u2.rating_deviation, u2.rating_volatility, u2.rating_matches)

                gw1 = m.p1_game_wins or (2 if m.winner_id == m.player1_id else 0)
                gw2 = m.p2_game_wins or (2 if m.winner_id == m.player2_id else 0)

                if m.result == MatchResult.DRAW:
                    nr1, nr2 = rate_draw(r1, r2)
                elif m.winner_id == m.player1_id:
                    nr1, nr2 = rate_1vs1(r1, r2, gw1, gw2)
                else:
                    nr2, nr1 = rate_1vs1(r2, r1, gw2, gw1)

                u1.rating = round(nr1.value, 1)
                u1.rating_deviation = round(nr1.rd, 1)
                u1.rating_volatility = round(nr1.volatility, 4)
                u1.rating_matches = nr1.matches
                u1.last_rated_at = datetime.now()

                u2.rating = round(nr2.value, 1)
                u2.rating_deviation = round(nr2.rd, 1)
                u2.rating_volatility = round(nr2.volatility, 4)
                u2.rating_matches = nr2.matches
                u2.last_rated_at = datetime.now()

            await session.commit()

    async def generate_next_round(self, tournament_id: int) -> str:
        async with self._repos() as (session, trepo, tprepo, mrepo, _):
            tournament = await trepo.get_by_id(tournament_id)
            if tournament is None:
                return "Torneo non trovato."
            if tournament.status != TournamentStatus.ACTIVE:
                return "Il torneo non e attivo."

            current_round = await mrepo.get_current_round(tournament_id)
            matches = await mrepo.get_by_tournament(tournament_id)

            pending = [
                m for m in matches
                if m.round_number == current_round
                and m.player2_id is not None
                and m.result is None
            ]
            if pending:
                return (
                    f"Ci sono ancora {len(pending)} partite del round "
                    f"{current_round} senza risultato."
                )

            if tournament.round_count and current_round >= tournament.round_count:
                tournament.status = TournamentStatus.COMPLETED
                tournament.ended_at = datetime.now()
                session.add(tournament)
                await session.commit()
                await self._update_ratings(tournament_id)
                return (
                    f"Torneo **{tournament.name}** completato!"
                )

            next_round = current_round + 1
            players = await tprepo.get_by_tournament(tournament_id)
            pairings = PairingEngine.generate_round(
                players, matches, next_round
            )

            for pairing in pairings:
                match = Match(
                    tournament_id=tournament_id,
                    round_number=next_round,
                    player1_id=pairing.player1_id,
                    player2_id=pairing.player2_id,
                    table_number=pairing.table_number,
                )
                session.add(match)
            await session.commit()

            return (
                f"Round {next_round} generato! "
                f"{len(pairings)} incontri."
            )

    async def get_standings(
        self, tournament_id: int
    ) -> list[StandingsEntry] | str:
        async with self._repos() as (session, trepo, tprepo, mrepo, urepo):
            tournament = await trepo.get_by_id(tournament_id)
            if tournament is None:
                return "Torneo non trovato."

            matches = await mrepo.get_by_tournament(tournament_id)
            # A dropped player stays in the standings (marked) only if they
            # played: their matches count toward opponents' OMW, as in Wizards
            # tournaments. Someone who left during registration doesn't.
            played = {m.player1_id for m in matches} | {m.player2_id for m in matches}
            players = [
                tp for tp in await tprepo.get_by_tournament(tournament_id, include_dropped=True)
                if not tp.dropped or tp.id in played
            ]

            name_cache: dict[int, str] = {}
            deck_cache: dict[int, str] = {}

            for tp in players:
                name_cache[tp.id] = self._resolve_name(tp)
                deck_cache[tp.id] = tp.deck_name or ""

            def get_name(tp_id: int) -> str:
                return name_cache.get(tp_id, f"Giocatore #{tp_id}")

            def get_deck(tp_id: int) -> str:
                return deck_cache.get(tp_id, "")

            entries = StandingsCalculator.compute(
                tournament_id, players, matches, get_name, get_deck
            )
            return entries

    async def get_current_round(self, tournament_id: int) -> int:
        async with self._repos() as (session, _, _, mrepo, _):
            return await mrepo.get_current_round(tournament_id)

    async def get_matches(self, tournament_id: int) -> list[Match]:
        async with self._repos() as (session, _, _, mrepo, _):
            return await mrepo.get_by_tournament(tournament_id)

    async def get_leaderboard(self, limit: int = 50) -> list[dict]:
        async with self._repos() as (session, _, _, _, urepo):
            users = await urepo.get_leaderboard(limit)
            result = []
            for u in users:
                name = f"<@{u.discord_id}>"
                if u.nome:
                    name = f"{u.nome} ({name})"
                lb_rating = u.rating - 2 * u.rating_deviation
                result.append({
                    "discord_id": u.discord_id,
                    "name": name,
                    "rating": round(u.rating, 1),
                    "rd": round(u.rating_deviation, 1),
                    "matches": u.rating_matches,
                    "lb_rating": round(lb_rating, 1),
                })
            return result
