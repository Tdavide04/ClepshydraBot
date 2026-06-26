import asyncio
import discord

from discord.ext import commands
from discord import app_commands

from utils.arena_overrides import (
    update_spg_overrides,
    invalidate_override_cache
)

# ==========================================
# COG
# ==========================================

class SPGOverrideUpdater(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    # ======================================
    # UPDATE COMMAND
    # ======================================

    @app_commands.command(
        name="update_spg_overrides",
        description="Aggiorna automaticamente gli override SPG"
    )
    @app_commands.default_permissions(administrator=True)
    async def update_spg_overrides_command(
        self,
        interaction: discord.Interaction
    ):

        await interaction.response.defer(ephemeral=True)

        try:

            invalidate_override_cache()

            added = await update_spg_overrides(set_code="spg")

            if not added:
                await interaction.followup.send(
                    "✅ Nessun nuovo override trovato.",
                    ephemeral=True
                )
                return

            lines = [
                f"• **{name}** → {rarity}"
                for name, rarity in added[:20]
            ]

            text = "\n".join(lines)

            if len(added) > 20:
                text += f"\n_...e altre {len(added) - 20} carte_"

            await interaction.followup.send(
                f"✅ Override aggiornati ({len(added)} totali):\n\n{text}",
                ephemeral=True
            )

        except Exception as e:

            import traceback
            traceback.print_exc()

            await interaction.followup.send(
                f"❌ Errore durante l'update:\n`{e}`",
                ephemeral=True
            )


# ==========================================
# SETUP
# ==========================================

async def setup(bot):
    await bot.add_cog(SPGOverrideUpdater(bot))