from datetime import datetime
import discord, os
from discord.ext import commands
from config.config import DISCORD_TOKEN, GUILD_ID, VERSION
from database import init_db, close_db
from utils.card_cache import periodic_save_loop


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
        self.loop.create_task(periodic_save_loop())

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

    async def close(self):
        await close_db()
        await super().close()
bot = ClepshydraBotte()
bot.run(DISCORD_TOKEN)
