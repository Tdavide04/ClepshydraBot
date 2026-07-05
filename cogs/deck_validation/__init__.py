import discord
from discord.ext import commands

from cogs.deck_validation.validators import parse_decklist
from cogs.deck_validation.service import ArtisanService


class ArtisanDeckCheckModal(
    discord.ui.Modal,
    title="Controllo Mazzo Artisan"
):
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

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import traceback
        traceback.print_exception(type(error), error, error.__traceback__)
        try:
            await interaction.followup.send(
                "Errore interno durante l'analisi.", ephemeral=True
            )
        except Exception:
            pass

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Analisi del mazzo Artisan in corso...", ephemeral=True
        )

        try:
            entries, total_cards, _ = parse_decklist(self.deck_list.value)
            deck_name = self.titolo.value.strip() or "ARTISAN DECK"
            await self.service.validate_and_publish(
                interaction, entries, deck_name, total_cards
            )
        except Exception:
            import traceback
            traceback.print_exc()
            await interaction.edit_original_response(
                content="Errore durante l'analisi del mazzo."
            )


class Tournament(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.service = ArtisanService(bot)

    @discord.app_commands.command(
        name="artisan_check_deck",
        description="Analizza se il tuo deck e legale per Artisan Arena"
    )
    async def artisan_check_deck(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ArtisanDeckCheckModal(self.service))


async def setup(bot):
    await bot.add_cog(Tournament(bot))