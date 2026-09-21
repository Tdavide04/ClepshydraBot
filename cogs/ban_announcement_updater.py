import discord

from discord.ext import commands
from discord import app_commands

from utils.ban_announcement import check_ban_announcement_updates, send_ban_announcement_log
from utils.permissions import is_admin

# ==========================================
# COG
# ==========================================

class BanAnnouncementUpdater(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    # ======================================
    # CHECK COMMAND
    # ======================================

    @app_commands.command(
        name="forced_ban_announcement_check",
        description="Ricontrolla subito l'ultimo Banned and Restricted Announcement (gira anche da solo ogni giorno)"
    )
    @is_admin()
    async def forced_ban_announcement_check_command(
        self,
        interaction: discord.Interaction
    ):

        await interaction.response.defer(ephemeral=True)

        try:

            results = await check_ban_announcement_updates(force=True)

            if not results:
                await interaction.followup.send(
                    "✅ Nessun Banned and Restricted Announcement trovato sul sitemap (o fetch fallito, vedi log console).",
                    ephemeral=True
                )
                return

            logger = self.bot.get_cog("Logger")
            result = results[0]

            if logger:
                await send_ban_announcement_log(logger, result, user=interaction.user, forced=True)

            esito = "interpretato correttamente" if result["changes"] is not None else "NON interpretabile, vedi WARN nel canale log"
            await interaction.followup.send(
                f"✅ Ricontrollato {result['url']} ({esito}). Dettagli nel canale log.",
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
    await bot.add_cog(BanAnnouncementUpdater(bot))
