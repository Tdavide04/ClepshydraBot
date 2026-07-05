from typing import Generic, TypeVar, Type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):

    def __init__(self, session: AsyncSession, model: Type[T]):
        self.session = session
        self.model = model

    async def get_by_id(self, id: int) -> T | None:
        return await self.session.get(self.model, id)

    async def list_all(self) -> list[T]:
        result = await self.session.execute(select(self.model))
        return list(result.scalars().all())

    async def add(self, instance: T) -> T:
        self.session.add(instance)
        await self.session.commit()
        await self.session.refresh(instance)
        return instance

    async def delete(self, instance: T) -> None:
        await self.session.delete(instance)
        await self.session.commit()

    async def count(self) -> int:
        result = await self.session.execute(
            select(self.model).with_only_columns(self.model.id)
        )
        return len(result.all())
