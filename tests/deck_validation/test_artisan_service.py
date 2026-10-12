import asyncio
import urllib.parse

import pytest

import cogs.deck_validation.service as service_module
import utils.card_cache as card_cache
from cogs.deck_validation.models import DeckEntry
from cogs.deck_validation.service import ArtisanService, ScryfallUnavailable
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
        if isinstance(prints, Exception):
            raise prints
        # Nessuna stampa nota = 404 di Scryfall, che _get_with_retry traduce in
        # un risultato vuoto (carta senza stampe Arena).
        return {"data": prints or []}
    return fake_get


@pytest.fixture
def isolated_arena_legal_cache(monkeypatch):
    """_ARENA_LEGAL_CACHE e' di modulo: ogni test parte vuoto."""
    monkeypatch.setattr(service_module, "_ARENA_LEGAL_CACHE", {})


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

    def test_banned_double_faced_card_matches_front_face_only(self, isolated_db):
        """Regressione: cards.txt/banned_cards salva le double-faced col nome
        completo ("Fronte // Retro"), ma parse_decklist() tronca al fronte
        quando legge il deck dell'utente. Senza espandere la banlist con la
        sola meta' fronte, check_banlist() non faceva mai match per queste
        carte, che restavano bandite solo sulla carta ma mai catturate."""
        async def scenario():
            await _seed_banlist("Test Front // Test Back")
            service = ArtisanService()
            service._post_with_retry = _make_fake_post({})  # non deve essere chiamato
            # come lo produrrebbe parse_decklist(): solo il fronte
            entries = [DeckEntry(quantity=60, name="Test Front", is_sideboard=False)]
            return await service.validate_deck(entries, "Test Deck", 60)

        result = run_with_db(scenario)
        assert result.banned_cards == ["Test Front"]
        assert result.is_valid is False

    def test_public_banlist_listing_is_not_expanded(self, isolated_db):
        """La sola meta' fronte sintetica (vedi test sopra) deve restare
        confinata alla cache di ArtisanService: BanlistRepository.get_all_for_format()
        (usata anche da /banlist, il comando pubblico) deve elencare solo le
        carte davvero salvate nel DB, non varianti derivate."""
        async def scenario():
            await _seed_banlist("Test Front // Test Back")
            session = get_session()
            try:
                repo = BanlistRepository(session)
                return await repo.get_all_for_format()
            finally:
                await session.close()

        raw = run_with_db(scenario)
        # cards.txt reale viene comunque importato nel DB di test (_migrate_banlist
        # gira su ogni init_db()), quindi raw contiene anche quelle ~219 carte:
        # controlliamo presenza/assenza, non uguaglianza dell'intero set.
        assert "test front // test back" in raw
        assert "test front" not in raw

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


class TestScryfallUnavailable:

    def test_prints_lookup_failure_is_a_service_error_not_an_illegal_card(
        self, isolated_db, isolated_arena_legal_cache
    ):
        """Regressione: un errore di rete sulla ricerca stampe salvava la carta
        come illegale in _ARENA_LEGAL_CACHE fino al riavvio del bot."""
        async def scenario():
            card = _card_data("Flaky Card")
            service = ArtisanService()
            service._post_with_retry = _make_fake_post({"Flaky Card": card})
            service._get_with_retry = _make_fake_get({"Flaky Card": ScryfallUnavailable("HTTP 503")})
            entries = [DeckEntry(quantity=60, name="Flaky Card", is_sideboard=False)]
            failed = await service.validate_deck(entries, "Test Deck", 60)

            # Scryfall torna disponibile: la stessa carta deve risultare legale.
            service._get_with_retry = _make_fake_get({"Flaky Card": [_arena_print("common")]})
            recovered = await service.validate_deck(entries, "Test Deck", 60)
            return failed, recovered

        failed, recovered = run_with_db(scenario)
        assert failed.service_error
        assert failed.is_valid is False
        assert failed.illegal_rarity_cards == []
        assert failed.invalid_cards == []
        assert recovered.service_error is None
        assert recovered.is_valid is True

    def test_collection_failure_is_a_service_error_not_missing_cards(
        self, isolated_db, isolated_arena_legal_cache
    ):
        """Un blocco /cards/collection fallito faceva risultare le carte come
        'Carte non trovate' invece di segnalare Scryfall non raggiungibile."""
        async def scenario():
            service = ArtisanService()

            async def failing_post(session, url, payload, label, retries=5):
                raise ScryfallUnavailable("timeout")

            service._post_with_retry = failing_post
            entries = [DeckEntry(quantity=60, name="Any Card", is_sideboard=False)]
            return await service.validate_deck(entries, "Test Deck", 60)

        result = run_with_db(scenario)
        assert result.service_error
        assert result.invalid_cards == []
        assert result.main_count == 60

    def test_card_without_arena_prints_is_still_illegal_and_cached(
        self, isolated_db, isolated_arena_legal_cache
    ):
        """Il 404 di Scryfall (nessuna stampa Arena) resta un esito legittimo:
        carta illegale, e va ricordato."""
        async def scenario():
            card = _card_data("Paper Only")
            service = ArtisanService()
            service._post_with_retry = _make_fake_post({"Paper Only": card})
            service._get_with_retry = _make_fake_get({})
            entries = [DeckEntry(quantity=60, name="Paper Only", is_sideboard=False)]
            return await service.validate_deck(entries, "Test Deck", 60)

        result = run_with_db(scenario)
        assert result.service_error is None
        assert result.illegal_rarity_cards == ["Paper Only"]
        assert service_module._ARENA_LEGAL_CACHE["oracle-Paper Only"] is False


class FakeResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status = status
        self._payload = payload or {}
        self.headers = headers or {}

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """Restituisce in ordine le risposte (o solleva le eccezioni) date."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def request(self, method, url, json=None):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None
    monkeypatch.setattr(service_module.asyncio, "sleep", instant)


class TestRequestWithRetry:

    def test_404_is_an_empty_result(self, no_sleep):
        session = FakeSession(FakeResponse(404))
        data = asyncio.run(ArtisanService()._get_with_retry(session, "u", "x"))
        assert data == {"data": []}

    def test_server_error_is_retried_then_succeeds(self, no_sleep):
        session = FakeSession(FakeResponse(503), FakeResponse(200, {"data": [1]}))
        data = asyncio.run(ArtisanService()._get_with_retry(session, "u", "x"))
        assert data == {"data": [1]}
        assert session.calls == 2

    def test_exhausted_retries_raise_scryfall_unavailable(self, no_sleep):
        session = FakeSession(*[asyncio.TimeoutError() for _ in range(3)])
        with pytest.raises(ScryfallUnavailable):
            asyncio.run(ArtisanService()._post_with_retry(session, "u", {}, "x", retries=3))
        assert session.calls == 3
