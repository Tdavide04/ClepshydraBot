from sqlalchemy import select
from database.models import User
from repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):

    def __init__(self, session):
        super().__init__(session, User)

    async def get_by_discord_id(self, discord_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.discord_id == discord_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, discord_id: int) -> User:
        user = await self.get_by_discord_id(discord_id)
        if user is not None:
            return user
        user = User(discord_id=discord_id)
        return await self.add(user)

    async def get_leaderboard(self, limit: int = 50) -> list[User]:
        from sqlalchemy import desc
        result = await self.session.execute(
            select(User)
            .where(User.rating_matches > 0)
            .order_by(desc(User.rating))
            .limit(limit)
        )
        return list(result.scalars().all())
