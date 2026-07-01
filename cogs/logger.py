import discord, os
from discord.ext import commands
from datetime import datetime

from config.config import LOG_CHANNEL_ID

class Logger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log_channel_id = LOG_CHANNEL_ID
        
        self.levels = {
            "INFO": ("🟢", discord.Color.green()),
            "WARN": ("🟡", discord.Color.gold()),
            "ERROR": ("🔴", discord.Color.red()),
            "DEBUG": ("🔵", discord.Color.blue())
        }

    async def send_log(self, level, event, user=None, channel=None, info=None):
        """Metodo universale per inviare log con pattern specifico."""
        emoji, color = self.levels.get(level.upper(), self.levels["INFO"])
        
        try:
            log_channel = await self.bot.fetch_channel(self.log_channel_id)
            
            description = ""
            if user: description += f"**User:** {user.mention} ({user.name})\n"
            if channel: description += f"**Channel:** {channel.mention if hasattr(channel, 'mention') else channel}\n"
            if info:
                if info.strip().startswith("**"):
                    description += f"{info}\n"
                else:
                    description += f"**Info:** {info}\n"
            
            embed = discord.Embed(
                title=f"{emoji} [{level.upper()}] | {event.upper()}",
                description=description.strip(),
                color=color,
                timestamp=datetime.now()
            )
            
            embed.set_footer(text=f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            await log_channel.send(embed=embed)
            
        except Exception as e:
            print(f"⚠️ Errore logger: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Esempio di log INFO al nuovo ingresso."""
        role = discord.utils.get(member.guild.roles, name="Viandante")
        status = "❌ Ruolo non trovato"
        
        if role:
            try:
                await member.add_roles(role)
                status = "✅ Ruolo 'Viandante' assegnato"
                level = "INFO"
            except discord.Forbidden:
                status = "⚠️ Errore permessi"
                level = "ERROR"
        else:
            level = "WARN"

        await self.send_log(
            level=level,
            event="MEMBER_JOIN",
            user=member,
            info=f"Nuovo ingresso nel server.\n**Stato:** {status}"
        )

async def setup(bot):
    await bot.add_cog(Logger(bot))