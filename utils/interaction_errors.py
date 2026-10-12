"""
interaction_errors.py

Gestione comune degli errori non previsti nelle interazioni Discord (slash
command, modal, view). Senza, un'eccezione dopo un `defer()` lasciava
l'utente su "sta pensando..." per sempre e finiva solo in console, mai nel
canale log - e' cosi' che si manifestava il crash di /classifica corretto
nella 3.5.5.

Usata da tre punti d'ingresso, perche' discord.py instrada gli errori in
modo diverso per ciascuno:
- slash command: CommandTree.on_error, agganciato da cogs/error_handler.py
- modal: Modal.on_error, via ReportingModal
- view (bottoni/select): View.on_error, via ReportingView
"""

import traceback
from datetime import datetime

import discord

USER_MESSAGE = "❌ Si è verificato un errore inatteso. Lo staff è stato avvisato."

# Coda del traceback nel log Discord: la description di un embed ha un limite
# di 4096 caratteri, e la parte utile (dove e' esploso) e' in fondo.
_TRACEBACK_TAIL_CHARS = 1500


async def _notify_user(interaction: discord.Interaction) -> None:
    """Risponde all'utente in modo ephemeral, scegliendo tra risposta
    iniziale e followup a seconda che l'interazione abbia gia' risposto (es.
    dopo un defer). Non solleva: l'interazione puo' essere gia' scaduta, e
    un errore qui non deve impedire il log allo staff."""

    try:
        if interaction.response.is_done():
            await interaction.followup.send(USER_MESSAGE, ephemeral=True)
        else:
            await interaction.response.send_message(USER_MESSAGE, ephemeral=True)
    except discord.HTTPException:
        pass


async def report_interaction_error(
    interaction: discord.Interaction, error: Exception, source: str
) -> None:
    """Avvisa l'utente, logga l'errore nel canale log (ERROR
    INTERACTION_ERROR) e stampa il traceback completo in console.
    `source` identifica il punto d'ingresso (es. '/classifica', 'form
    InviaDeckModal')."""

    # CommandInvokeError (slash command) incapsula l'eccezione reale.
    original = getattr(error, "original", error)
    formatted = "".join(traceback.format_exception(type(original), original, original.__traceback__))

    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INTERACTION ERROR] {source}: "
        f"{type(original).__name__}: {original}"
    )
    print(formatted)

    await _notify_user(interaction)

    logger = interaction.client.get_cog("Logger") if interaction.client else None
    if logger:
        await logger.send_log(
            level="ERROR",
            event="INTERACTION_ERROR",
            user=interaction.user,
            channel=interaction.channel,
            info=(
                f"**Origine:** {source}\n"
                f"**Errore:** `{type(original).__name__}: {original}`\n"
                f"```{formatted[-_TRACEBACK_TAIL_CHARS:]}```"
            ),
        )


class ReportingModal(discord.ui.Modal):
    """Modal base: un errore in on_submit viene segnalato invece di
    mostrare all'utente il generico 'Something went wrong' di Discord."""

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_interaction_error(interaction, error, f"form {type(self).__name__}")


class ReportingView(discord.ui.View):
    """View base: stesso trattamento per i callback di bottoni e select."""

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        await report_interaction_error(interaction, error, f"view {type(self).__name__}")
