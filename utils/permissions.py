import discord
from discord.app_commands import check


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        from config.config import ADMIN_ROLE

        if not interaction.guild:
            await interaction.response.send_message(
                "Questo comando può essere usato solo in un server.",
                ephemeral=True
            )
            return False

        role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
        if role is None:
            await interaction.response.send_message(
                f"Ruolo **{ADMIN_ROLE}** non trovato. "
                "Contatta l'amministratore.",
                ephemeral=True
            )
            return False

        if isinstance(interaction.user, discord.Member) and role in interaction.user.roles:
            return True

        await interaction.response.send_message(
            f"Devi avere il ruolo **{ADMIN_ROLE}** per usare questo comando.",
            ephemeral=True
        )
        return False

    return check(predicate)
