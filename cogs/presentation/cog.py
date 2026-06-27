import discord
from discord.ext import commands

from config.config import FINAL_ROLE, INITIAL_ROLE, PRESENTATION_CHANNEL_ID

class PresentationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        logger = self.bot.get_cog('Logger')
        role = discord.utils.get(member.guild.roles, name=INITIAL_ROLE)
        try:
            if role:
                await member.add_roles(role)
        except discord.errors.HTTPException as e:
            if logger:
                level = "WARN" if e.status == 429 else "ERROR"
                await logger.send_log(
                    level=level,
                    event="JOIN_ROLE_FAIL",
                    user=member,
                    info=f"Errore API {e.status}: {e.text}"
                )
        except discord.errors.Forbidden:
            if logger:
                await logger.send_log(
                    level="ERROR",
                    event="JOIN_PERMISSIONS_FAIL",
                    user=member,
                    info="Il bot non ha permessi per gestire il ruolo Viandante."
                )

        channel = discord.utils.get(member.guild.text_channels, name=PRESENTATION_CHANNEL_ID)
        if channel:
            await channel.send(
                f"Benvenuto {member.mention}! Attualmente hai una visione limitata dei canali del server. "
                f"Usa `/presentati` per sbloccare tutte le funzionalita del server. "
                f"All'interno troverai canali specifici per ogni formato di Magic Arena, canali generali e qualche nuovo amico.",
                delete_after=300.0
            )

    @discord.app_commands.command(name="presentati", description="Apri il modulo di presentazione")
    async def presentati(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "Questo comando puo essere usato solo in un server.",
                ephemeral=True
            )

        member = interaction.user
        if isinstance(member, discord.Member):
            if any(role.name == FINAL_ROLE for role in member.roles):
                return await interaction.response.send_message(
                    "Sei gia verificato!",
                    ephemeral=True
                )

        from cogs.presentation.modals import BasicPresentationModal
        modal = BasicPresentationModal(interaction.user.id if hasattr(interaction.user, 'id') else 0)
        await interaction.response.send_modal(modal)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        channel_name = getattr(message.channel, "name", None)
        if channel_name != PRESENTATION_CHANNEL_ID:
            return

        logger = self.bot.get_cog('Logger')
        try:
            await message.delete()
            if logger:
                await logger.send_log(
                    level="INFO",
                    event="MESSAGE_DELETE",
                    user=message.author,
                    channel=message.channel,
                    info=f"Messaggio rimosso: {message.content}"
                )
            await message.channel.send(
                f"Attenzione {message.author.mention}, in questo canale puoi solo usare `/presentati`. "
                f"I messaggi normali vengono eliminati.",
                delete_after=15
            )
        except Exception as e:
            if logger:
                await logger.send_log(
                    level="ERROR",
                    event="CLEANUP_ERROR",
                    channel=message.channel,
                    info=f"Impossibile eliminare messaggio: {str(e)}"
                )


async def setup(bot):
    await bot.add_cog(PresentationCog(bot))