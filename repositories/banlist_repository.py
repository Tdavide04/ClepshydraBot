from sqlalchemy import select, delete
from database.models import BannedCard
from repositories.base import BaseRepository


class BanlistRepository(BaseRepository[BannedCard]):

    def __init__(self, session):
        super().__init__(session, BannedCard)

    async def get_all_for_format(self, format: str = "Artisan") -> set[str]:
        result = await self.session.execute(
            select(BannedCard.card_name)
            .where(BannedCard.format == format)
        )
        return {row[0].lower() for row in result.all()}

    async def add_card(self, card_name: str, format: str = "Artisan") -> BannedCard:
        card = BannedCard(card_name=card_name.strip(), format=format)
        return await self.add(card)

    async def remove_card(self, card_name: str) -> bool:
        result = await self.session.execute(
            delete(BannedCard).where(BannedCard.card_name == card_name.strip())
        )
        await self.session.commit()
        return result.rowcount > 0

    async def count(self) -> int:
        result = await self.session.execute(select(BannedCard.id))
        return len(result.all())

    async def import_from_file(self, path: str) -> int:
        count = await self.count()
        if count > 0:
            return 0

        imported = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                name = line.strip()
                if not name:
                    continue
                card = BannedCard(card_name=name, format="Artisan")
                self.session.add(card)
                imported += 1
        await self.session.commit()
        return imported
