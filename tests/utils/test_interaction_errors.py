import asyncio

import discord
from discord import app_commands

from cogs.error_handler import ErrorHandler
from utils.interaction_errors import (
    USER_MESSAGE,
    ReportingModal,
    ReportingView,
    report_interaction_error,
)


def run(coro):
    return asyncio.run(coro)


class FakeLogger:
    def __init__(self):
        self.calls = []

    async def send_log(self, **kwargs):
        self.calls.append(kwargs)


class FakeClient:
    def __init__(self, logger):
        self.logger = logger

    def get_cog(self, name):
        return self.logger if name == "Logger" else None


class FakeResponse:
    def __init__(self, done: bool):
        self.done = done
        self.sent = []

    def is_done(self):
        return self.done

    async def send_message(self, content, ephemeral=False):
        self.sent.append((content, ephemeral))
        self.done = True


class FakeFollowup:
    def __init__(self, raises: Exception | None = None):
        self.sent = []
        self.raises = raises

    async def send(self, content, ephemeral=False):
        if self.raises:
            raise self.raises
        self.sent.append((content, ephemeral))


class FakeCommand:
    name = "classifica"
    qualified_name = "classifica"


class FakeInteraction:
    """Only the attributes read by report_interaction_error()/ErrorHandler."""

    def __init__(self, done=False, logger=None, followup_raises=None):
        self.response = FakeResponse(done)
        self.followup = FakeFollowup(followup_raises)
        self.client = FakeClient(logger)
        self.user = "utente"
        self.channel = "canale"
        self.command = FakeCommand()


def _raise_and_capture(exc: Exception) -> Exception:
    try:
        raise exc
    except Exception as e:
        return e


class TestReportInteractionError:
    def test_replies_with_send_message_when_not_yet_responded(self):
        interaction = FakeInteraction(done=False, logger=FakeLogger())

        run(report_interaction_error(interaction, _raise_and_capture(KeyError(1)), "/classifica"))

        assert interaction.response.sent == [(USER_MESSAGE, True)]
        assert interaction.followup.sent == []

    def test_replies_with_followup_after_a_defer(self):
        """The /classifica crash case: defer() already done, so only the
        followup can reply - without it, the user was left on 'thinking'."""
        interaction = FakeInteraction(done=True, logger=FakeLogger())

        run(report_interaction_error(interaction, _raise_and_capture(KeyError(1)), "/classifica"))

        assert interaction.followup.sent == [(USER_MESSAGE, True)]
        assert interaction.response.sent == []

    def test_logs_an_error_with_source_and_exception(self):
        logger = FakeLogger()
        interaction = FakeInteraction(logger=logger)

        run(report_interaction_error(interaction, _raise_and_capture(KeyError(1)), "/classifica"))

        assert len(logger.calls) == 1
        call = logger.calls[0]
        assert call["level"] == "ERROR"
        assert call["event"] == "INTERACTION_ERROR"
        assert "/classifica" in call["info"]
        assert "KeyError" in call["info"]

    def test_unwraps_command_invoke_error(self):
        logger = FakeLogger()
        interaction = FakeInteraction(logger=logger)
        original = _raise_and_capture(ValueError("boom"))
        wrapped = app_commands.CommandInvokeError(FakeCommand(), original)

        run(report_interaction_error(interaction, wrapped, "/classifica"))

        assert "ValueError: boom" in logger.calls[0]["info"]

    def test_expired_interaction_still_logs_to_staff(self):
        logger = FakeLogger()
        expired = discord.HTTPException(
            type("R", (), {"status": 404, "reason": "Not Found"})(), "Unknown interaction"
        )
        interaction = FakeInteraction(done=True, logger=logger, followup_raises=expired)

        run(report_interaction_error(interaction, _raise_and_capture(KeyError(1)), "/classifica"))

        assert len(logger.calls) == 1


class TestReportingBaseClasses:
    def test_modal_on_error_reports_with_class_name(self):
        class DemoModal(ReportingModal, title="Demo"):
            pass

        logger = FakeLogger()

        async def scenario():
            await DemoModal().on_error(FakeInteraction(logger=logger), _raise_and_capture(KeyError(1)))

        run(scenario())

        assert "form DemoModal" in logger.calls[0]["info"]

    def test_view_on_error_reports_with_class_name(self):
        class DemoView(ReportingView):
            pass

        logger = FakeLogger()

        async def scenario():
            await DemoView().on_error(FakeInteraction(logger=logger), _raise_and_capture(KeyError(1)), None)

        run(scenario())

        assert "view DemoView" in logger.calls[0]["info"]


class TestErrorHandlerCog:
    def test_check_failure_is_not_logged_as_an_error(self):
        """@is_admin() already replies on its own: no ERROR log for a missing
        permission, and no second reply."""
        logger = FakeLogger()
        interaction = FakeInteraction(done=True, logger=logger)

        run(ErrorHandler(bot=None).on_app_command_error(interaction, app_commands.CheckFailure()))

        assert logger.calls == []
        assert interaction.followup.sent == []

    def test_unexpected_error_is_reported_with_command_name(self):
        logger = FakeLogger()
        interaction = FakeInteraction(done=True, logger=logger)
        error = app_commands.CommandInvokeError(FakeCommand(), _raise_and_capture(KeyError(1)))

        run(ErrorHandler(bot=None).on_app_command_error(interaction, error))

        assert "/classifica" in logger.calls[0]["info"]
        assert interaction.followup.sent == [(USER_MESSAGE, True)]
