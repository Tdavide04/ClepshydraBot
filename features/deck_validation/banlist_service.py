from core.results import ServiceResult
from database import get_session
from features.deck_validation.banlist_repository import BanlistRepository
from features.deck_validation.service import invalidate_banlist_cache

DB_UNAVAILABLE_MESSAGE = "Database non disponibile."


class BanlistService:
    """Staff operations on the Artisan banlist (/banlist, /banlist_aggiungi,
    /banlist_rimuovi). Every change invalidates the module-level banlist cache
    shared by the ArtisanService instances, so the next deck validation
    reloads it from the DB: this is the one place that does it."""

    async def list_cards(self) -> list[str] | None:
        """Banned card names, sorted. None when the DB isn't initialized."""
        session = get_session()
        if session is None:
            return None
        try:
            return sorted(await BanlistRepository(session).get_all_for_format())
        finally:
            await session.close()

    async def add_card(self, card_name: str) -> ServiceResult:
        card_name = card_name.strip()
        if not card_name:
            return ServiceResult(False, "Indica il nome della carta da bannare.")
        session = get_session()
        if session is None:
            return ServiceResult(False, DB_UNAVAILABLE_MESSAGE)
        try:
            repo = BanlistRepository(session)
            # Checked first: card_name is UNIQUE, so a duplicate would raise
            # IntegrityError, and the constraint is case-sensitive.
            if await repo.contains(card_name):
                return ServiceResult(False, f"Carta **{card_name}** è già nella banlist.")
            await repo.add_card(card_name)
        finally:
            await session.close()
        invalidate_banlist_cache()
        return ServiceResult(True, f"Carta **{card_name}** aggiunta alla banlist.")

    async def remove_card(self, card_name: str) -> ServiceResult:
        card_name = card_name.strip()
        session = get_session()
        if session is None:
            return ServiceResult(False, DB_UNAVAILABLE_MESSAGE)
        try:
            removed = await BanlistRepository(session).remove_card(card_name)
        finally:
            await session.close()
        if not removed:
            return ServiceResult(False, f"Carta **{card_name}** non trovata nella banlist.")
        invalidate_banlist_cache()
        return ServiceResult(True, f"Carta **{card_name}** rimossa dalla banlist.")
