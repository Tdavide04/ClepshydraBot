import discord

from discord.ext import commands
from discord import app_commands

from utils.arena_event_schedule import check_event_schedule_updates, send_event_schedule_log
from utils.permissions import is_admin

# ==========================================
# COG
# ==========================================

class ArenaEventScheduleUpdater(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    # ======================================
    # CHECK COMMAND
    # ======================================

    @app_commands.command(
        name="forced_event_schedule_check",
        description="Forza subito un ricontrollo della pagina Event Schedule Arena piu' recente (gira anche da solo ogni giorno)"
    )
    @is_admin()
    async def forced_event_schedule_check_command(
        self,
        interaction: discord.Interaction
    ):

        await interaction.response.defer(ephemeral=True)

        try:

            results = await check_event_schedule_updates(force=True)

            if not results:
                await interaction.followup.send(
                    "✅ Nessuna pagina Event Schedule trovata sul sitemap (o fetch fallito, vedi log console).",
                    ephemeral=True
                )
                return

            logger = self.bot.get_cog("Logger")
            result = results[0]

            if logger:
                await send_event_schedule_log(logger, result, user=interaction.user, forced=True)

            esito = "interpretata correttamente" if result["categories"] is not None else "NON interpretabile, vedi WARN nel canale log"
            await interaction.followup.send(
                f"✅ Ricontrollata {result['url']} ({esito}). Dettagli nel canale log.",
                ephemeral=True
            )

        except Exception as e:

            import traceback
            traceback.print_exc()

            await interaction.followup.send(
                f"❌ Errore durante il controllo:\n`{e}`",
                ephemeral=True
            )


# ==========================================
# SETUP
# ==========================================

async def setup(bot):
    await bot.add_cog(ArenaEventScheduleUpdater(bot))
