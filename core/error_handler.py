from discord import app_commands
from discord.ext import commands

from core.interaction_errors import report_interaction_error


class ErrorHandler(commands.Cog):
    """Hooks CommandTree.on_error: the only place where discord.py routes
    unhandled slash-command exceptions. The previous handler is restored
    when the cog is unloaded."""

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
            # @is_admin() already replies on its own before failing: reply
            # here only if no check did. No log: a missing permission is not
            # a bot error.
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Non hai i permessi per usare questo comando.", ephemeral=True
                )
            return

        name = interaction.command.qualified_name if interaction.command else "?"
        await report_interaction_error(interaction, error, f"/{name}")


async def setup(bot):
    await bot.add_cog(ErrorHandler(bot))
