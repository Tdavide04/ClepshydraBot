import discord

from discord.ext import commands
from discord import app_commands

from utils.arena_event_schedule import (
    MONTHS_IT,
    build_month_calendar,
    check_event_schedule_updates,
    send_event_schedule_log,
)
from utils.event_calendar_image_generator import EventCalendarImageGenerator
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
        description="Ricontrolla subito l'Event Schedule Arena piu' recente (gira anche da solo ogni giorno)"
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

    # ======================================
    # CALENDAR IMAGE PREVIEW (comando di test)
    # ======================================

    @app_commands.command(
        name="preview_calendario_eventi",
        description="Genera e pubblica il calendario eventi Arena, un'immagine per mese"
    )
    @is_admin()
    async def preview_calendario_eventi_command(
        self,
        interaction: discord.Interaction
    ):
        """Ricontrolla la pagina Event Schedule piu' recente e pubblica le
        immagini calendario generate come messaggio normale (non ephemeral)
        nel canale in cui viene invocato - non allegate al canale log, per
        restare uno strumento manuale distinto dal flusso automatico in
        send_event_schedule_log()."""

        await interaction.response.defer(ephemeral=False)

        try:

            results = await check_event_schedule_updates(force=True)

            if not results or results[0]["categories"] is None:
                await interaction.followup.send(
                    "❌ Nessuna pagina Event Schedule interpretabile trovata (vedi log console).",
                    ephemeral=True
                )
                return

            result = results[0]
            month_calendar = build_month_calendar(result["categories"])

            if not month_calendar:
                await interaction.followup.send(
                    "⚠️ Nessuna voce con data riconosciuta in "
                    f"{result['url']} — calendario vuoto.",
                    ephemeral=True
                )
                return

            files = []
            month_labels = []
            for (year, month), category_entries in sorted(month_calendar.items()):
                png = EventCalendarImageGenerator.create_month_calendar(
                    year, month, category_entries
                )
                files.append(discord.File(png, filename=f"calendario_{year}_{month:02d}.png"))
                month_labels.append(f"{MONTHS_IT.get(month, month)} {year}")

            caption = (
                f"📅 **Calendario eventi Arena** — {', '.join(month_labels)}\n"
                f"Fonte: <{result['url']}>"
            )
            await interaction.followup.send(caption, files=files)

        except Exception as e:

            import traceback
            traceback.print_exc()

            await interaction.followup.send(
                f"❌ Errore durante la generazione del calendario:\n`{e}`",
                ephemeral=True
            )


# ==========================================
# SETUP
# ==========================================

async def setup(bot):
    await bot.add_cog(ArenaEventScheduleUpdater(bot))
