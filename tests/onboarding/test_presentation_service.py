import asyncio
from dataclasses import replace
from types import SimpleNamespace

from cogs.presentation.models import PRESENTATION_DATA_STORE, PresentationData
from cogs.presentation.service import PresentationService
from config.config import PRESENTATION_CHANNEL_ID


def run(coro):
    return asyncio.run(coro)


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(jump_url="https://discord.com/channels/1/1/1")


class FakeMember:
    """Not a discord.Member, so publish() resolves it through the guild, the
    same path it takes when the interaction user is a plain discord.User."""

    def __init__(self, guild, roles):
        self.guild = guild
        self.roles = list(roles)
        self.name = "member"
        self.display_name = "Member"
        self.display_avatar = SimpleNamespace(url="https://cdn.example/avatar.png")

    async def add_roles(self, *roles):
        self.roles.extend(roles)

    async def remove_roles(self, *roles):
        for role in roles:
            self.roles.remove(role)


class FakeGuild:
    def __init__(self, channel):
        self.viandante = SimpleNamespace(name="Viandante")
        self.planeswalker = SimpleNamespace(name="Planeswalker")
        self.roles = [self.viandante, self.planeswalker]
        self.channel = channel
        self.member = FakeMember(self, [self.viandante])

    def get_channel(self, channel_id):
        return self.channel if channel_id == PRESENTATION_CHANNEL_ID else None

    def get_member(self, user_id):
        return self.member


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content)


def make_interaction(guild):
    return SimpleNamespace(user=SimpleNamespace(id=42), guild=guild, followup=FakeFollowup())


def make_data(**overrides):
    valid = PresentationData(
        user_id=42,
        nome="Mario",
        nickname_arena="mario#12345",
        anno_nascita="1995",
        professione="Sviluppatore",
        provenienza="Roma",
        anno_cartaceo="2010",
        anno_arena="2019",
        colori=["blu"],
        gilde=["izzet"],
        formati_construed=["standard"],
    )
    return replace(valid, **overrides)


def make_service():
    return PresentationService(SimpleNamespace(get_cog=lambda name: None))


class TestPublish:
    def test_valid_presentation_is_posted_and_promotes_the_member(self):
        guild = FakeGuild(FakeChannel())
        data = make_data()
        PRESENTATION_DATA_STORE[data.user_id] = data

        result = run(make_service().publish(make_interaction(guild), data))

        assert result.ok
        assert "Benvenuto" in result.message
        assert len(guild.channel.sent) == 1
        assert guild.member.roles == [guild.planeswalker]
        assert data.user_id not in PRESENTATION_DATA_STORE

    def test_invalid_presentation_is_refused_without_a_welcome(self):
        """Regression: publish() sent the validation errors itself and returned
        None, so the view went on to send "Benvenuto tra i Planeswalker!"
        to a member whose presentation was refused and who got no role."""
        guild = FakeGuild(FakeChannel())
        interaction = make_interaction(guild)

        result = run(make_service().publish(interaction, make_data(anno_nascita="abcd")))

        assert not result.ok
        assert "Anno di nascita" in result.message
        assert "Benvenuto" not in result.message
        assert interaction.followup.sent == [], "the caller sends the outcome, not publish()"
        assert guild.channel.sent == []
        assert guild.member.roles == [guild.viandante]

    def test_missing_presentation_channel_is_refused_without_a_welcome(self):
        """Regression: with the channel missing, publish() returned silently
        and the member was welcomed although nothing was posted."""
        guild = FakeGuild(channel=None)

        result = run(make_service().publish(make_interaction(guild), make_data()))

        assert not result.ok
        assert "Benvenuto" not in result.message
        assert guild.member.roles == [guild.viandante]
