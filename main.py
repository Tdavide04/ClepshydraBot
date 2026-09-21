import discord
import os
import sys
from discord.ext import commands
from config.config import DISCORD_TOKEN, GUILD_ID, VERSION
from database import init_db, close_db
from utils.card_cache import periodic_save_loop
from utils.arena_overrides import periodic_spg_refresh_loop
from utils.arena_event_schedule import get_latest_known_event_schedule, periodic_event_schedule_check_loop
from utils.ban_announcement import get_latest_known_ban_announcement, periodic_ban_announcement_check_loop


class ClepshydraBotte(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await init_db()

        for entry in os.listdir('./cogs'):
            path = os.path.join('./cogs', entry)
            if entry.endswith('.py') and entry != '__init__.py':
                await self.load_extension(f'cogs.{entry[:-3]}')
            elif os.path.isdir(path) and os.path.exists(os.path.join(path, '__init__.py')):
                await self.load_extension(f'cogs.{entry}')

        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)

        logger = self.get_cog('Logger')
        if logger:
            await logger.send_log(
                level="DEBUG",
                event="SYSTEM_STARTUP",
                info=(
                    f"**Nome:** ClepshydraBotte\n"
                    f"**Versione:** {VERSION}\n"
                    f"**Stato:** Online e Operativo\n"
                    f"**Database:** Inizializzato\n"
                    f"**Comandi Sync:** {len(synced)}\n"
                    f"**Versione Library:** {discord.__version__}"
                )
            )

            # Riepilogo di stato SOLO nel canale log (non community): quale
            # sia l'ultima pagina Event Schedule/Banned and Restricted GIA'
            # nota al bot, letta dagli state file su disco senza fare
            # richieste di rete. Distinto dal check periodico vero e proprio
            # (che invece interroga il sitemap e scatta poco dopo, appena i
            # create_task sotto partono) - qui interessa solo mostrare cosa
            # il bot sa gia' ad ogni riavvio, utile per verificare al volo
            # se lo stato salvato risulta quello aspettato.
            event_schedule_state = get_latest_known_event_schedule()
            ban_announcement_state = get_latest_known_ban_announcement()
            await logger.send_log(
                level="INFO",
                event="STARTUP_STATUS",
                info=(
                    f"**Ultima pagina Event Schedule nota:** "
                    f"{event_schedule_state['url'] or 'nessuna (stato vuoto)'}\n"
                    f"**Ultimo Banned and Restricted Announcement noto:** "
                    f"{ban_announcement_state['url'] or 'nessuno (stato vuoto)'}"
                )
            )

        # Avviati DOPO il log di startup: create_task schedula solo, non
        # esegue subito, ma i loro primi giri (check SPG/Event Schedule,
        # entrambi HTTP e non istantanei) possono comunque superare in
        # velocita' l'await di tree.sync() sopra se partono prima di lui -
        # osservato in produzione, il log SYSTEM_STARTUP arrivava dopo i log
        # dei controlli automatici invece che prima.
        self.loop.create_task(periodic_save_loop())
        self.loop.create_task(periodic_spg_refresh_loop(self))
        self.loop.create_task(periodic_event_schedule_check_loop(self))
        self.loop.create_task(periodic_ban_announcement_check_loop(self))

    async def close(self):
        await close_db()
        await super().close()


bot = ClepshydraBotte()

try:
    bot.run(DISCORD_TOKEN)
except discord.LoginFailure:
    print("FATAL: token Discord non valido o scaduto. Il bot non puo' avviarsi.", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"FATAL: avvio del bot fallito: {e}", file=sys.stderr)
    sys.exit(1)
