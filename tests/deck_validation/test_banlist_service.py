import asyncio

from database import close_db, init_db
from features.deck_validation.banlist_service import BanlistService

# isolated_db and isolated_banlist_cache come from conftest.py. init_db()
# imports the real seeds/banlist.txt into the test DB, so these tests use card
# names that aren't in it.


def run_with_db(scenario):
    async def _wrapper():
        await init_db()
        try:
            return await scenario()
        finally:
            await close_db()

    return asyncio.run(_wrapper())


class TestAddCard:
    def test_added_card_is_listed(self, isolated_db):
        async def scenario():
            service = BanlistService()
            outcome = await service.add_card("Test Banned Card")
            return outcome, await service.list_cards()

        outcome, cards = run_with_db(scenario)

        assert outcome.ok
        assert "aggiunta" in outcome.message
        assert "test banned card" in cards

    def test_duplicate_is_refused_whatever_the_case(self, isolated_db):
        """Regression: banned_cards.card_name is UNIQUE, so adding a card twice
        raised IntegrityError and staff got the generic error message. A
        different case slipped past the constraint and stored a duplicate."""

        async def scenario():
            service = BanlistService()
            await service.add_card("Test Banned Card")
            same = await service.add_card("Test Banned Card")
            other_case = await service.add_card("test BANNED card")
            return same, other_case, await service.list_cards()

        same, other_case, cards = run_with_db(scenario)

        assert not same.ok
        assert not other_case.ok
        assert "già" in same.message
        assert cards.count("test banned card") == 1

    def test_blank_name_is_refused(self, isolated_db):
        async def scenario():
            return await BanlistService().add_card("   ")

        assert not run_with_db(scenario).ok


class TestRemoveCard:
    def test_removal_ignores_case(self, isolated_db):
        """Regression: /banlist lists names lowercased, but removal matched the
        stored name exactly, so removing a card as shown by /banlist failed."""

        async def scenario():
            service = BanlistService()
            await service.add_card("Test Banned Card")
            outcome = await service.remove_card("test banned card")
            return outcome, await service.list_cards()

        outcome, cards = run_with_db(scenario)

        assert outcome.ok
        assert "rimossa" in outcome.message
        assert "test banned card" not in cards

    def test_unknown_card_is_reported(self, isolated_db):
        async def scenario():
            return await BanlistService().remove_card("Never Banned Card")

        outcome = run_with_db(scenario)

        assert not outcome.ok
        assert "non trovata" in outcome.message


class TestDatabaseUnavailable:
    def test_every_operation_refuses_without_a_database(self, isolated_db):
        async def scenario():
            service = BanlistService()
            return (
                await service.list_cards(),
                await service.add_card("Test Banned Card"),
                await service.remove_card("Test Banned Card"),
            )

        cards, added, removed = asyncio.run(scenario())

        assert cards is None
        assert not added.ok and "Database non disponibile" in added.message
        assert not removed.ok and "Database non disponibile" in removed.message
