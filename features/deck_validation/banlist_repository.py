from sqlalchemy import delete, func, select

from core.repository_base import BaseRepository
from database.models import BannedCard


class BanlistRepository(BaseRepository[BannedCard]):
    def __init__(self, session):
        super().__init__(session, BannedCard)

    async def get_all_for_format(self, format: str = "Artisan") -> set[str]:
        result = await self.session.execute(select(BannedCard.card_name).where(BannedCard.format == format))
        return {row[0].lower() for row in result.all()}

    async def add_card(self, card_name: str, format: str = "Artisan") -> BannedCard:
        card = BannedCard(card_name=card_name.strip(), format=format)
        return await self.add(card)

    async def contains(self, card_name: str) -> bool:
        """Case-insensitive, like the deck check, which compares lowercased names."""
        result = await self.session.execute(
            select(BannedCard.id).where(func.lower(BannedCard.card_name) == card_name.strip().lower())
        )
        return result.first() is not None

    async def remove_card(self, card_name: str) -> bool:
        result = await self.session.execute(
            delete(BannedCard).where(func.lower(BannedCard.card_name) == card_name.strip().lower())
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
        # Blocking read is fine here: called once at startup by _migrate_banlist(), on an empty table only.
        with open(path, encoding="utf-8") as f:  # noqa: ASYNC230
            for line in f:
                name = line.strip()
                if not name:
                    continue
                card = BannedCard(card_name=name, format="Artisan")
                self.session.add(card)
                imported += 1
        await self.session.commit()
        return imported
