import discord, os
from cogs.presentation.models import PresentationData, PRESENTATION_DATA_STORE
from cogs.presentation.embeds import build_published_embed
from cogs.presentation.validators import valida_presentazione
from config.config import FINAL_ROLE, INITIAL_ROLE, PRESENTATION_CHANNEL_ID

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

        channel = guild.get_channel(PRESENTATION_CHANNEL_ID)

        if channel is None:
            if logger:
                await logger.send_log(
                    level="ERROR",
                    event="PRESENTATION_CHANNEL_MISSING",
                    user=member,
                    info=f"Canale presentazioni con ID {PRESENTATION_CHANNEL_ID} non trovato."
                )
            return

        embed = build_published_embed(member, data)

        presentation_msg = await channel.send(
            embed=embed
        )

        await self._assign_final_role(member, data)

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

    async def _assign_final_role(self, member, data: PresentationData):
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

        # Pulizia storage temporaneo
        if data.user_id in PRESENTATION_DATA_STORE:
            del PRESENTATION_DATA_STORE[data.user_id]