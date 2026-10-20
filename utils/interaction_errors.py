"""
interaction_errors.py

Shared handling of unexpected errors in Discord interactions (slash
commands, modals, views). Without it, an exception after a `defer()` left
the user on "thinking..." forever and only reached the console, never the
log channel - that is how the /classifica crash fixed in 3.5.5 showed up.

Used by three entry points, because discord.py routes errors differently
for each:
- slash command: CommandTree.on_error, agganciato da cogs/error_handler.py
- modal: Modal.on_error, via ReportingModal
- view (bottoni/select): View.on_error, via ReportingView
"""

import traceback

import discord

from utils.console import log

USER_MESSAGE = "❌ Si è verificato un errore inatteso. Lo staff è stato avvisato."

# Traceback tail in the Discord log: an embed description is capped at 4096
# characters, and the useful part (where it blew up) is at the end.
_TRACEBACK_TAIL_CHARS = 1500


async def _notify_user(interaction: discord.Interaction) -> None:
    """Replies to the user ephemerally, choosing between the initial
    response and a followup depending on whether the interaction has already
    been answered (e.g. after a defer). Never raises: the interaction may
    have expired already, and a failure here must not prevent the staff log."""

    try:
        if interaction.response.is_done():
            await interaction.followup.send(USER_MESSAGE, ephemeral=True)
        else:
            await interaction.response.send_message(USER_MESSAGE, ephemeral=True)
    except discord.HTTPException:
        pass


async def report_interaction_error(interaction: discord.Interaction, error: Exception, source: str) -> None:
    """Notifies the user, logs the error to the log channel (ERROR
    INTERACTION_ERROR) and prints the full traceback to the console.
    `source` identifies the entry point (e.g. '/classifica', 'form
    InviaDeckModal')."""

    # CommandInvokeError (slash command) wraps the real exception.
    original = getattr(error, "original", error)
    formatted = "".join(traceback.format_exception(type(original), original, original.__traceback__))

    log(f"[INTERACTION ERROR] {source}: {type(original).__name__}: {original}")
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
                f"**Source:** {source}\n"
                f"**Error:** `{type(original).__name__}: {original}`\n"
                f"```{formatted[-_TRACEBACK_TAIL_CHARS:]}```"
            ),
        )


class ReportingModal(discord.ui.Modal):
    """Base modal: an error in on_submit gets reported instead of showing
    the user Discord's generic 'Something went wrong'."""

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_interaction_error(interaction, error, f"form {type(self).__name__}")


class ReportingView(discord.ui.View):
    """Base view: same treatment for button and select callbacks."""

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        await report_interaction_error(interaction, error, f"view {type(self).__name__}")
