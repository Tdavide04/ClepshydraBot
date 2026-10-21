from datetime import datetime

import discord
from discord.ext import commands

from cogs.deck_validation.service import ArtisanService
from cogs.deck_validation.validators import parse_decklist
from database import get_session
from repositories.banlist_repository import BanlistRepository
from utils.interaction_errors import ReportingModal
from utils.permissions import is_admin


class ArtisanDeckCheckModal(ReportingModal, title="Controllo Mazzo Artisan"):
    titolo = discord.ui.TextInput(
        label="Nome del tuo mazzo",
        placeholder="es. Mono Red Aggro",
        required=True,
        max_length=100,
    )

    deck_list = discord.ui.TextInput(
        label="Incolla la tua lista (60 Main + 15 Side)",
        style=discord.TextStyle.paragraph,
        placeholder="4 Experimental Confectioner / 3 Honey Mammoth ...",
        required=True,
        min_length=10,
        max_length=2000,
    )

    def __init__(self, service: ArtisanService):
        super().__init__()
        self.service = service

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("Analisi del mazzo Artisan in corso...", ephemeral=True)

        # No try/except here: an unexpected error reaches
        # ReportingModal.on_error, which notifies the user AND staff (it used
        # to be printed to the console only).
        entries, total_cards, _ = parse_decklist(self.deck_list.value)
        deck_name = self.titolo.value.strip() or "ARTISAN DECK"
        await self.service.validate_and_publish(interaction, entries, deck_name, total_cards)


class DeckValidationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.service = ArtisanService(bot)

    async def _log(self, level, event, user=None, info=None):
        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.send_log(level=level, event=event, user=user, info=info)

    @discord.app_commands.command(
        name="artisan_check_deck", description="Analizza se il tuo deck e legale per Artisan Arena"
    )
    async def artisan_check_deck(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ArtisanDeckCheckModal(self.service))

    @discord.app_commands.command(name="banlist", description="Visualizza le carte bannate")
    async def banlist_lista(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer(ephemeral=False)

        session = get_session()
        if session is None:
            return await interaction.followup.send("Database non disponibile.", ephemeral=True)

        try:
            repo = BanlistRepository(session)
            cards = await repo.get_all_for_format()
            if not cards:
                await interaction.followup.send("Nessuna carta bannata.", ephemeral=True)
                return
            sorted_cards = sorted(cards)
            embed = discord.Embed(
                title=f"\U0001f6ab Banlist ({len(sorted_cards)} carte)",
                color=discord.Color.red(),
                timestamp=datetime.now(),
            )
            chunks = [sorted_cards[i : i + 30] for i in range(0, len(sorted_cards), 30)]
            for i, chunk in enumerate(chunks):
                name = "Carte" if len(chunks) == 1 else f"Carte (parte {i + 1})"
                embed.add_field(
                    name=name,
                    value="\n".join(f"\u2022 {c}" for c in chunk),
                    inline=False,
                )
            embed.set_footer(text="Formato: Artisan")
            await interaction.followup.send(embed=embed)
        finally:
            await session.close()

    @discord.app_commands.command(
        name="banlist_aggiungi", description="Aggiungi una carta alla banlist (admin)"
    )
    @is_admin()
    @discord.app_commands.describe(carta="Nome della carta da bannare")
    async def banlist_aggiungi(
        self,
        interaction: discord.Interaction,
        carta: str,
    ):
        await interaction.response.defer(ephemeral=True)
        session = get_session()
        if session is None:
            return await interaction.followup.send("Database non disponibile.", ephemeral=True)
        try:
            repo = BanlistRepository(session)
            await repo.add_card(carta)
            await self.service.reload_banlist()
            await self._log("INFO", "BANLIST_ADD", user=interaction.user, info=f"Added: {carta}")
            await interaction.followup.send(f"Carta **{carta}** aggiunta alla banlist.", ephemeral=True)
        finally:
            await session.close()

    @discord.app_commands.command(
        name="banlist_rimuovi", description="Rimuovi una carta dalla banlist (admin)"
    )
    @is_admin()
    @discord.app_commands.describe(carta="Nome della carta da rimuovere")
    async def banlist_rimuovi(
        self,
        interaction: discord.Interaction,
        carta: str,
    ):
        await interaction.response.defer(ephemeral=True)
        session = get_session()
        if session is None:
            return await interaction.followup.send("Database non disponibile.", ephemeral=True)
        try:
            repo = BanlistRepository(session)
            ok = await repo.remove_card(carta)
            if ok:
                await self.service.reload_banlist()
                await self._log("INFO", "BANLIST_REMOVE", user=interaction.user, info=f"Removed: {carta}")
                await interaction.followup.send(f"Carta **{carta}** rimossa dalla banlist.", ephemeral=True)
            else:
                await interaction.followup.send(
                    f"Carta **{carta}** non trovata nella banlist.", ephemeral=True
                )
        finally:
            await session.close()


async def setup(bot):
    await bot.add_cog(DeckValidationCog(bot))
