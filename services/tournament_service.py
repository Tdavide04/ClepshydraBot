from datetime import datetime

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
from services.standings import StandingsCalculator, StandingsEntry
from services.rating import Rating, rate_1vs1, rate_draw
from config.config import TEST_MODE, GUILD_ID


class TournamentService:

    def __init__(self, bot=None):
        self.bot = bot

    def _get_repos(self):
        session = get_session()
        return (
            session,
            TournamentRepository(session),
            TournamentPlayerRepository(session),
            MatchRepository(session),
            UserRepository(session),
        )

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
        session, repo, _, _, _ = self._get_repos()
        try:
            tournament = Tournament(
                name=name,
                format=format,
                max_players=max_players,
            )
            result = await repo.add(tournament)
            return result
        finally:
            await session.close()

    async def list_tournaments(self) -> list[Tournament]:
        session, repo, _, _, _ = self._get_repos()
        try:
            return await repo.list_all()
        finally:
            await session.close()

    async def list_tournaments_with_counts(self) -> list[tuple[Tournament, int]]:
        session, trepo, tprepo, _, _ = self._get_repos()
        try:
            tournaments = await trepo.list_all()
            tournaments.sort(key=lambda t: t.created_at or datetime.min, reverse=True)
            result = []
            for t in tournaments:
                count = await tprepo.count_in_tournament(t.id)
                result.append((t, count))
            return result
        finally:
            await session.close()

    async def register_player(
        self, tournament_id: int, discord_id: int, deck_name: str | None = None
    ) -> str:
        session, trepo, tprepo, _, urepo = self._get_repos()
        try:
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

            count = await tprepo.count_in_tournament(tournament_id)
            tp = TournamentPlayer(
                tournament_id=tournament_id,
                user_id=user.id,
                seed=count + 1,
                deck_name=deck_name,
            )
            await tprepo.add(tp)
            deck_info = f" con **{deck_name}**" if deck_name else ""
            return f"Iscrizione confermata al torneo **{tournament.name}** (seed #{count + 1}){deck_info}."
        finally:
            await session.close()

    async def start_tournament(self, tournament_id: int) -> str:
        session, trepo, tprepo, mrepo, _ = self._get_repos()
        try:
            tournament = await trepo.get_with_players(tournament_id)
            if tournament is None:
                return "Torneo non trovato."
            if tournament.status != TournamentStatus.REGISTRATION:
                return "Il torneo e gia iniziato o concluso."

            players = await tprepo.get_by_tournament(tournament_id)
            if len(players) < 2:
                return "Servono almeno 2 giocatori per iniziare."

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
        finally:
            await session.close()

    async def find_tournament(self, identifier: str) -> Tournament | None:
        session, trepo, _, _, _ = self._get_repos()
        try:
            if identifier.isdigit():
                return await trepo.get_by_id(int(identifier))
            return await trepo.find_by_name(identifier)
        finally:
            await session.close()

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        session, trepo, _, _, _ = self._get_repos()
        try:
            return await trepo.get_by_id(tournament_id)
        finally:
            await session.close()

    async def is_player_registered(
        self, tournament_id: int, discord_id: int
    ) -> bool:
        session, _, tprepo, _, urepo = self._get_repos()
        try:
            user = await urepo.get_by_discord_id(discord_id)
            if user is None:
                return False
            existing = await tprepo.get_by_tournament_and_user(
                tournament_id, user.id
            )
            return existing is not None and not existing.dropped
        finally:
            await session.close()

    async def get_registered_players(
        self, tournament_id: int
    ) -> list[TournamentPlayer]:
        session, _, tprepo, _, _ = self._get_repos()
        try:
            return await tprepo.get_by_tournament(tournament_id)
        finally:
            await session.close()

    async def unregister_player(
        self, tournament_id: int, discord_id: int
    ) -> str:
        session, trepo, tprepo, _, urepo = self._get_repos()
        try:
            tournament = await trepo.get_by_id(tournament_id)
            if tournament is None:
                return "Torneo non trovato."
            if tournament.status != TournamentStatus.REGISTRATION:
                return "Non puoi uscire da un torneo gi\u00e0 iniziato o completato."

            user = await urepo.get_by_discord_id(discord_id)
            if user is None:
                return "Non sei iscritto a questo torneo."

            tp = await tprepo.get_by_tournament_and_user(tournament_id, user.id)
            if tp is None:
                return "Non sei iscritto a questo torneo."

            tp.dropped = True
            session.add(tp)
            await session.commit()
            return f"Sei uscito dal torneo **{tournament.name}**."
        finally:
            await session.close()

    async def force_drop_player(
        self, tournament_id: int, discord_id: int
    ) -> str:
        session, trepo, tprepo, mrepo, urepo = self._get_repos()
        try:
            tournament = await trepo.get_by_id(tournament_id)
            if tournament is None:
                return "Torneo non trovato."
            if tournament.status != TournamentStatus.ACTIVE:
                return "Il torneo non e attivo."

            user = await urepo.get_by_discord_id(discord_id)
            if user is None:
                return "Giocatore non trovato."

            tp = await tprepo.get_by_tournament_and_user(tournament_id, user.id)
            if tp is None or tp.dropped:
                return "Giocatore non iscritto o gia rimosso."

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
        finally:
            await session.close()

    async def force_conclude_tournament(self, tournament_id: int) -> str:
        session, trepo, _, _, _ = self._get_repos()
        try:
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
        finally:
            await session.close()

    async def find_pending_match_for_user(
        self, tournament_id: int, discord_id: int
    ) -> Match | None:
        session, _, tprepo, mrepo, urepo = self._get_repos()
        try:
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
        finally:
            await session.close()

    async def submit_result(
        self,
        match_id: int,
        winner_tp_id: int | None,
        result: str | None,
        p1_game_wins: int | None = None,
        p2_game_wins: int | None = None,
    ) -> str:
        session, _, _, mrepo, _ = self._get_repos()
        try:
            match = await mrepo.get_by_id(match_id)
            if match is None:
                return "Partita non trovata."
            if match.result is not None:
                return "Risultato gia inserito per questa partita."
            if match.player2_id is None:
                return "Questa e una partita di bye."

            if result is not None:
                try:
                    match.result = MatchResult(result)
                except ValueError:
                    return f"Risultato non valido: {result}"
                if winner_tp_id is not None:
                    if winner_tp_id not in (match.player1_id, match.player2_id):
                        return "Il vincitore non e uno dei giocatori della partita."
                    match.winner_id = winner_tp_id
            elif winner_tp_id is not None:
                if winner_tp_id not in (match.player1_id, match.player2_id):
                    return "Il vincitore non e uno dei giocatori della partita."
                match.winner_id = winner_tp_id
                match.result = MatchResult.WIN

            match.p1_game_wins = p1_game_wins
            match.p2_game_wins = p2_game_wins

            session.add(match)
            await session.commit()
            return "Risultato registrato!"
        finally:
            await session.close()

    async def _update_ratings(self, tournament_id: int):
        session, _, tprepo, mrepo, urepo = self._get_repos()
        try:
            tournament = await session.get(Tournament, tournament_id)
            if tournament is None:
                return

            players = await tprepo.get_by_tournament(tournament_id)
            matches = await mrepo.get_by_tournament(tournament_id)

            user_map: dict[int, User] = {}
            for tp in players:
                if tp.user_id:
                    user = await session.get(User, tp.user_id)
                    if user:
                        user_map[tp.user_id] = user

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
        finally:
            await session.close()

    async def generate_next_round(self, tournament_id: int) -> str:
        session, trepo, tprepo, mrepo, _ = self._get_repos()
        try:
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
        finally:
            await session.close()

    async def get_standings(
        self, tournament_id: int
    ) -> list[StandingsEntry] | str:
        session, trepo, tprepo, mrepo, urepo = self._get_repos()
        try:
            tournament = await trepo.get_by_id(tournament_id)
            if tournament is None:
                return "Torneo non trovato."

            players = await tprepo.get_by_tournament(tournament_id)
            matches = await mrepo.get_by_tournament(tournament_id)

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
        finally:
            await session.close()

    async def get_current_round(self, tournament_id: int) -> int:
        session, _, _, mrepo, _ = self._get_repos()
        try:
            return await mrepo.get_current_round(tournament_id)
        finally:
            await session.close()

    async def get_matches(self, tournament_id: int) -> list[Match]:
        session, _, _, mrepo, _ = self._get_repos()
        try:
            return await mrepo.get_by_tournament(tournament_id)
        finally:
            await session.close()

    async def get_leaderboard(self, limit: int = 50) -> list[dict]:
        session, _, _, _, urepo = self._get_repos()
        try:
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
        finally:
            await session.close()
