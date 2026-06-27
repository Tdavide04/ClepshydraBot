import discord
from cogs.presentation.models import PresentationData
from cogs.presentation.embeds import build_published_embed, build_message_content
from cogs.presentation.validators import valida_presentazione


PRESENTATION_CHANNEL = "presentazioni"
INITIAL_ROLE = "Viandante"
FINAL_ROLE = "Planeswalker"


class PresentationService:
    def __init__(self, bot):
        self.bot = bot
        self.logger = None

    def _get_logger(self):
        if not self.logger:
            self.logger = self.bot.get_cog('Logger')
        return self.logger

    async def publish(self, interaction: discord.Interaction, data: PresentationData):
        member = interaction.user

        if isinstance(member, discord.Member):
            guild = member.guild
        else:
            guild = interaction.guild
            if not guild:
                raise ValueError("Impossibile trovare il server.")

            member = guild.get_member(data.user_id)
            if not member:
                member = await guild.fetch_member(data.user_id)

        missing, errors = valida_presentazione(data)
        logger = self._get_logger()

        if missing or errors:
            if logger:
                await logger.send_log(
                    level="WARN",
                    event="VERIFICA_FALLITA",
                    user=member,
                    info=(
                        f"Campi mancanti: {', '.join(missing)} "
                        f"Campi invalidi: {', '.join(errors)}"
                    )
                )

            msg = "❌ **Ci sono problemi nella tua presentazione.**\n\n"
            if missing:
                msg += "📌 **Campi mancanti:**\n" + "\n".join(f"• {c}" for c in missing) + "\n\n"
            if errors:
                msg += "⚠️ **Campi con valori non validi:**\n" + "\n".join(f"• {c}" for c in errors) + "\n\n"

            await interaction.followup.send(msg, ephemeral=True)
            return

        guild = member.guild
        channel = discord.utils.get(guild.text_channels, name=PRESENTATION_CHANNEL)

        presentation_msg = None
        if channel:
            content = build_message_content(data)
            embed = build_published_embed(member, data)
            presentation_msg = await channel.send(content=content, embed=embed)

        await self._assign_final_role(member)

        if logger:
            info = f"Utente promosso a {FINAL_ROLE}"
            if presentation_msg:
                info += f"\n**Link:** [Presentation]({presentation_msg.jump_url})"
            await logger.send_log(
                level="INFO",
                event="PRESENTAZIONE_COMPLETATA",
                user=member,
                info=info
            )

    async def _assign_initial_role(self, member):
        initial_role = discord.utils.get(member.guild.roles, name=INITIAL_ROLE)
        if initial_role and initial_role not in member.roles:
            try:
                await member.add_roles(initial_role)
            except discord.errors.Forbidden:
                logger = self._get_logger()
                if logger:
                    await logger.send_log(
                        level="ERROR",
                        event="INITIAL_ROLE_FAIL",
                        user=member,
                        info="Il bot non ha permessi per assegnare il ruolo Viandante."
                    )

    async def _assign_final_role(self, member):
        initial_role = discord.utils.get(member.guild.roles, name=INITIAL_ROLE)
        final_role = discord.utils.get(member.guild.roles, name=FINAL_ROLE)

        try:
            if initial_role and initial_role in member.roles:
                await member.remove_roles(initial_role)
            if final_role:
                await member.add_roles(final_role)
        except discord.errors.Forbidden:
            logger = self._get_logger()
            if logger:
                await logger.send_log(
                    level="ERROR",
                    event="ROLE_TRANSITION_FAIL",
                    user=member,
                    info="Il bot non ha permessi per gestire i ruoli."
                )