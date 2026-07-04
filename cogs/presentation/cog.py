import re
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

        channel = member.guild.get_channel(PRESENTATION_CHANNEL_ID)
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

        if message.channel.id != PRESENTATION_CHANNEL_ID:
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
                    info=self._build_delete_info(message)
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

    def _format_content(self, message):
        if not message.content:
            return "[Solo allegati]"

        content = message.content

        for role in message.role_mentions:
            content = content.replace(f'<@&{role.id}>', f'@{role.name}')

        content = re.sub(r'<@&(\d+)>', r'@_\1', content)

        return content

    def _get_message_type(self, message):
        types = set()

        if message.content:
            types.add("Testo")

        if message.content and re.search(r'https?://', message.content):
            types.add("Link")

        if message.mentions or message.role_mentions or message.channel_mentions:
            types.add("Mention")

        has_image = False
        has_gif = False
        has_video = False
        has_audio = False
        has_file = False

        for a in message.attachments:
            ct = (a.content_type or "").lower()
            fn = a.filename.lower()
            if 'gif' in ct or fn.endswith('.gif'):
                has_gif = True
            elif ct.startswith('image/') or fn.endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
                has_image = True
            elif ct.startswith('video/') or fn.endswith(('.mp4', '.webm', '.mov', '.avi')):
                has_video = True
            elif ct.startswith('audio/') or fn.endswith(('.mp3', '.wav', '.ogg', '.flac')):
                has_audio = True
            else:
                has_file = True

        if has_gif: types.add("GIF")
        if has_image: types.add("Immagine")
        if has_video: types.add("Video")
        if has_audio: types.add("Audio")
        if has_file: types.add("File")

        if message.stickers:
            types.add("Sticker")

        if message.embeds:
            types.add("Embed")

        return " + ".join(sorted(types)) if types else "Sconosciuto"

    def _get_attachments_info(self, message):
        if not message.attachments:
            return ""

        lines = []
        for a in message.attachments:
            lines.append(f"- {a.filename}")

        return "\n".join(lines)

    def _build_delete_info(self, message):
        parts = []

        msg_type = self._get_message_type(message)
        parts.append(f"**Type:** {msg_type}")

        content = self._format_content(message)
        parts.append(f"**Content:**\n{content}")

        attachments = self._get_attachments_info(message)
        if attachments:
            parts.append(f"**Attachments:**\n{attachments}")

        return "\n".join(parts)


async def setup(bot):
    await bot.add_cog(PresentationCog(bot))