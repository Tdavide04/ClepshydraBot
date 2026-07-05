from sqlalchemy import select, or_
from sqlalchemy.orm import joinedload

from database.models import (
    Tournament, TournamentPlayer, Match,
    TournamentStatus, MatchResult,
)
from repositories.base import BaseRepository



class TournamentRepository(BaseRepository[Tournament]):

    def __init__(self, session):
        super().__init__(session, Tournament)

    async def get_by_status(self, status: TournamentStatus) -> list[Tournament]:
        result = await self.session.execute(
            select(Tournament)
            .where(Tournament.status == status)
            .order_by(Tournament.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active(self) -> list[Tournament]:
        return await self.get_by_status(TournamentStatus.ACTIVE)

    async def get_open_for_registration(self) -> list[Tournament]:
        return await self.get_by_status(TournamentStatus.REGISTRATION)

    async def find_by_name(self, name: str) -> Tournament | None:
        result = await self.session.execute(
            select(Tournament)
            .where(Tournament.name.ilike(f"%{name}%"))
            .order_by(Tournament.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_with_players(self, tournament_id: int) -> Tournament | None:
        result = await self.session.execute(
            select(Tournament)
            .where(Tournament.id == tournament_id)
            .options(joinedload(Tournament.players))
        )
        return result.unique().scalar_one_or_none()


class TournamentPlayerRepository(BaseRepository[TournamentPlayer]):

    def __init__(self, session):
        super().__init__(session, TournamentPlayer)

    async def get_by_tournament(self, tournament_id: int) -> list[TournamentPlayer]:
        result = await self.session.execute(
            select(TournamentPlayer)
            .where(TournamentPlayer.tournament_id == tournament_id)
            .where(TournamentPlayer.dropped == False)
            .options(joinedload(TournamentPlayer.user))
            .order_by(TournamentPlayer.seed)
        )
        return list(result.unique().scalars().all())

    async def get_by_tournament_and_user(
        self, tournament_id: int, user_id: int
    ) -> TournamentPlayer | None:
        result = await self.session.execute(
            select(TournamentPlayer)
            .where(TournamentPlayer.tournament_id == tournament_id)
            .where(TournamentPlayer.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def count_in_tournament(self, tournament_id: int) -> int:
        result = await self.session.execute(
            select(TournamentPlayer)
            .where(TournamentPlayer.tournament_id == tournament_id)
            .where(TournamentPlayer.dropped == False)
        )
        return len(result.all())


class MatchRepository(BaseRepository[Match]):

    def __init__(self, session):
        super().__init__(session, Match)

    async def get_by_tournament(self, tournament_id: int) -> list[Match]:
        result = await self.session.execute(
            select(Match)
            .where(Match.tournament_id == tournament_id)
            .options(
                joinedload(Match.player1).joinedload(TournamentPlayer.user),
                joinedload(Match.player2).joinedload(TournamentPlayer.user),
            )
            .order_by(Match.round_number, Match.table_number)
        )
        return list(result.unique().scalars().all())

    async def get_by_tournament_and_round(
        self, tournament_id: int, round_number: int
    ) -> list[Match]:
        result = await self.session.execute(
            select(Match)
            .where(Match.tournament_id == tournament_id)
            .where(Match.round_number == round_number)
            .options(
                joinedload(Match.player1).joinedload(TournamentPlayer.user),
                joinedload(Match.player2).joinedload(TournamentPlayer.user),
            )
            .order_by(Match.table_number)
        )
        return list(result.unique().scalars().all())

    async def get_existing_pairings(
        self, tournament_id: int
    ) -> list[tuple[int, int]]:
        result = await self.session.execute(
            select(Match.player1_id, Match.player2_id)
            .where(Match.tournament_id == tournament_id)
            .where(Match.player2_id.isnot(None))
        )
        return [(r[0], r[1]) for r in result.all()]

    async def get_current_round(self, tournament_id: int) -> int:
        result = await self.session.execute(
            select(Match.round_number)
            .where(Match.tournament_id == tournament_id)
            .order_by(Match.round_number.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return row if row is not None else 0
