from discord import app_commands
from discord.ext import commands

from utils.interaction_errors import report_interaction_error


class ErrorHandler(commands.Cog):
    """Aggancia CommandTree.on_error: unico punto in cui discord.py
    instrada le eccezioni non gestite degli slash command. Il gestore
    precedente viene ripristinato allo scaricamento del cog."""

    def __init__(self, bot):
        self.bot = bot
        self._previous_on_error = None

    async def cog_load(self):
        self._previous_on_error = self.bot.tree.on_error
        self.bot.tree.on_error = self.on_app_command_error

    async def cog_unload(self):
        self.bot.tree.on_error = self._previous_on_error

    async def on_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.CheckFailure):
            # @is_admin() risponde gia' da se' prima di fallire: qui si
            # risponde solo se nessun check l'ha fatto. Nessun log: un
            # permesso mancante non e' un errore del bot.
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Non hai i permessi per usare questo comando.", ephemeral=True
                )
            return

        name = interaction.command.qualified_name if interaction.command else "?"
        await report_interaction_error(interaction, error, f"/{name}")


async def setup(bot):
    await bot.add_cog(ErrorHandler(bot))
