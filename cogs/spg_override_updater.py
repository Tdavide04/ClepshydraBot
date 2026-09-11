import discord

from discord.ext import commands
from discord import app_commands

from utils.arena_overrides import (
    update_spg_overrides,
    invalidate_override_cache
)
from utils.card_cache import invalidate_card
from utils.permissions import is_admin

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
        name="forced_rarity_refresh",
        description="Forza subito un controllo degli override SPG (gira anche da solo ogni settimana)"
    )
    @is_admin()
    async def forced_rarity_refresh_command(
        self,
        interaction: discord.Interaction
    ):

        await interaction.response.defer(ephemeral=True)

        try:

            invalidate_override_cache()

            added = await update_spg_overrides(set_code="spg")

            logger = self.bot.get_cog("Logger")

            if not added:
                await interaction.followup.send(
                    "✅ Nessun nuovo override trovato (già tutto aggiornato).",
                    ephemeral=True
                )
                if logger:
                    await logger.send_log(
                        level="INFO",
                        event="SPG_OVERRIDES_UPDATED",
                        user=interaction.user,
                        info="Controllo manuale forzato: nessun nuovo override trovato.",
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

            if logger:
                await logger.send_log(
                    level="INFO",
                    event="SPG_OVERRIDES_UPDATED",
                    user=interaction.user,
                    info=f"Controllo manuale forzato: {len(added)} nuovi override trovati\n\n{text}",
                )

        except Exception as e:

            import traceback
            traceback.print_exc()

            await interaction.followup.send(
                f"❌ Errore durante l'update:\n`{e}`",
                ephemeral=True
            )

    # ======================================
    # INVALIDATE SINGLE CARD COMMAND
    # ======================================

    @app_commands.command(
        name="invalidate_card_cache",
        description="Rimuove una carta dalla cache Scryfall, forzando un ricontrollo completo"
    )
    @is_admin()
    @app_commands.describe(carta="Nome esatto della carta da rimuovere dalla cache")
    async def invalidate_card_cache_command(
        self,
        interaction: discord.Interaction,
        carta: str
    ):
        await interaction.response.defer(ephemeral=True)

        removed = invalidate_card(carta)

        if removed:
            await interaction.followup.send(
                f"✅ **{carta}** rimossa dalla cache. Verrà ricontrollata da zero "
                f"(dati + legalità Artisan) alla prossima validazione.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"⚠️ **{carta}** non era presente in cache (nessuna azione necessaria).",
                ephemeral=True
            )


# ==========================================
# SETUP
# ==========================================

async def setup(bot):
    await bot.add_cog(SPGOverrideUpdater(bot))