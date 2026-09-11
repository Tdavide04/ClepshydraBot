import asyncio
import urllib.parse

import utils.card_cache as card_cache
from cogs.deck_validation.models import DeckEntry
from cogs.deck_validation.service import ArtisanService
from database import init_db, close_db, get_session
from repositories.banlist_repository import BanlistRepository

# isolated_db, isolated_card_cache, isolated_banlist_cache sono definite in
# conftest.py (condivise con test_card_cache.py).


def run_with_db(scenario):
    """Esegue init_db + logica + close_db in un unico event loop (stesso motivo
    di tests/tournament/test_tournament_service.py: aiosqlite lega le
    connessioni al loop che le ha create)."""
    async def _wrapper():
        await init_db()
        try:
            return await scenario()
        finally:
            await close_db()
    return asyncio.run(_wrapper())


async def _seed_banlist(*card_names: str) -> None:
    session = get_session()
    try:
        repo = BanlistRepository(session)
        for name in card_names:
            await repo.add_card(name)
    finally:
        await session.close()


def _card_data(name: str, *, cmc: float = 1.0) -> dict:
    """Dati Scryfall minimi per una carta di test."""
    query = urllib.parse.urlencode({"q": name})
    return {
        "name": name,
        "type_line": "Creature",
        "cmc": cmc,
        "oracle_id": f"oracle-{name}",
        "image_uris": {"small": f"https://img.example/{name}"},
        "prints_search_uri": f"https://api.scryfall.com/cards/search?{query}",
    }


def _arena_print(rarity: str, set_type: str = "expansion") -> dict:
    return {"rarity": rarity, "set_type": set_type, "name": "Fake Printing"}


def _make_fake_post(card_data_by_name: dict):
    async def fake_post(session, url, payload, label, retries=5):
        names = [ident["name"] for ident in payload["identifiers"]]
        return {"data": [card_data_by_name[n] for n in names if n in card_data_by_name]}
    return fake_post


def _make_fake_get(prints_by_name: dict):
    async def fake_get(session, url, label, retries=5):
        parsed = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
        name = q.replace(" game:arena", "").strip()
        prints = prints_by_name.get(name)
        if prints is None:
            return None
        return {"data": prints}
    return fake_get


class TestValidateDeck:

    def test_banned_card_short_circuits_before_scryfall(self, isolated_db):
        async def scenario():
            await _seed_banlist("Banned Card")
            service = ArtisanService()
            service._post_with_retry = _make_fake_post({})  # non deve essere chiamato
            entries = [DeckEntry(quantity=60, name="Banned Card", is_sideboard=False)]
            return await service.validate_deck(entries, "Test Deck", 60)

        result = run_with_db(scenario)
        assert result.banned_cards == ["Banned Card"]
        assert result.is_valid is False
        assert result.mainboard == []

    def test_valid_deck(self, isolated_db):
        async def scenario():
            main_card = _card_data("Test Common")
            side_card = _card_data("Test Uncommon")
            service = ArtisanService()
            service._post_with_retry = _make_fake_post({
                "Test Common": main_card,
                "Test Uncommon": side_card,
            })
            service._get_with_retry = _make_fake_get({
                "Test Common": [_arena_print("common")],
                "Test Uncommon": [_arena_print("uncommon")],
            })
            entries = [
                DeckEntry(quantity=60, name="Test Common", is_sideboard=False),
                DeckEntry(quantity=15, name="Test Uncommon", is_sideboard=True),
            ]
            return await service.validate_deck(entries, "Test Deck", 75)

        result = run_with_db(scenario)
        assert result.is_valid is True
        assert result.main_count == 60
        assert result.side_count == 15
        assert result.illegal_rarity_cards == []
        assert len(result.mainboard) == 1
        assert len(result.sideboard) == 1

    def test_illegal_rarity_card(self, isolated_db):
        async def scenario():
            rare_card = _card_data("Test Rare")
            service = ArtisanService()
            service._post_with_retry = _make_fake_post({"Test Rare": rare_card})
            service._get_with_retry = _make_fake_get({
                "Test Rare": [_arena_print("rare")],
            })
            entries = [DeckEntry(quantity=60, name="Test Rare", is_sideboard=False)]
            return await service.validate_deck(entries, "Test Deck", 60)

        result = run_with_db(scenario)
        assert result.is_valid is False
        assert result.illegal_rarity_cards == ["Test Rare"]

    def test_banlist_cache_shared_across_instances(self, isolated_db):
        """Regressione per il fix dello Step 1: il bot crea due ArtisanService
        separate (tournament_system e deck_validation). Un'invalidazione
        chiamata su una deve essere visibile dall'altra."""
        async def scenario():
            registering_service = ArtisanService()   # es. tournament_system
            checking_service = ArtisanService()       # es. deck_validation

            # nessuna carta bandita ancora: il deck passa il controllo banlist
            entries = [DeckEntry(quantity=60, name="Later Banned", is_sideboard=False)]
            card = _card_data("Later Banned")
            checking_service._post_with_retry = _make_fake_post({"Later Banned": card})
            checking_service._get_with_retry = _make_fake_get({
                "Later Banned": [_arena_print("common")],
            })
            first = await checking_service.validate_deck(entries, "Test Deck", 60)
            assert first.banned_cards == []

            # un admin bandisce la carta tramite la PRIMA istanza...
            session = get_session()
            try:
                repo = BanlistRepository(session)
                await repo.add_card("Later Banned")
            finally:
                await session.close()
            await registering_service.reload_banlist()

            # ...e la SECONDA istanza (mai toccata direttamente) deve vederlo subito
            return await checking_service.validate_deck(entries, "Test Deck", 60)

        result = run_with_db(scenario)
        assert result.banned_cards == ["Later Banned"]
        assert result.is_valid is False


class TestArtisanLegalTTL:

    def test_stale_cache_entry_is_rechecked(self, isolated_db):
        """Regressione per lo Step 3: una entry cacheata come legale ma scaduta
        (o senza timestamp, dato 'legacy') deve essere ri-verificata via
        Scryfall invece di essere considerata valida a tempo indeterminato."""
        async def scenario():
            card = _card_data("Reprinted Card")
            # entry "legacy": artisan_legal=True ma nessun artisan_legal_checked_at
            card_cache.set_cached_card("Reprinted Card", {**card, "artisan_legal": True})

            service = ArtisanService()
            service._post_with_retry = _make_fake_post({"Reprinted Card": card})
            # la ristampa via API ora risulta rara: non piu' legale
            service._get_with_retry = _make_fake_get({
                "Reprinted Card": [_arena_print("rare")],
            })

            entries = [DeckEntry(quantity=60, name="Reprinted Card", is_sideboard=False)]
            return await service.validate_deck(entries, "Test Deck", 60)

        result = run_with_db(scenario)
        assert result.illegal_rarity_cards == ["Reprinted Card"], (
            "la entry legacy senza timestamp deve essere trattata come scaduta "
            "e ri-verificata, non presa per buona"
        )
