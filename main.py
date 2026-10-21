import sys

import discord
from discord.ext import commands

from config.config import DISCORD_TOKEN, GUILD_ID, VERSION
from database import close_db, init_db
from features.monitors.ban_announcement import (
    get_latest_known_ban_announcement,
    periodic_ban_announcement_check_loop,
)
from features.monitors.event_schedule import (
    get_latest_known_event_schedule,
    periodic_event_schedule_check_loop,
)
from utils.arena_overrides import periodic_spg_refresh_loop
from utils.card_cache import periodic_save_loop, save_cache

# Every extension the bot has, in load order. Listed by hand rather than discovered from the cogs/ folder, so
# that "which features exist" doesn't depend on the folder layout; tests/core/test_extensions.py fails if an
# extension module is missing from this list.
EXTENSIONS = [
    "core.logger",
    "core.error_handler",
    "cogs.presentation",
    "cogs.deck_validation",
    "cogs.spg_override_updater",
    "features.monitors.event_schedule_cog",
    "features.monitors.ban_announcement_cog",
    "cogs.tournament_system",
]

# Extensions kept in the repo but not loaded: their slash commands disappear from Discord at the next
# tree.sync(). Remove an entry to bring the feature back.
DISABLED_COGS = {
    # Tournaments are hosted elsewhere since 4.0.0, the bot is a helper only
    # (docs/adr/0004-helper-only-tournaments-disabled.md).
    "cogs.tournament_system",
}


class ClepshydraBotte(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await init_db()

        for extension in EXTENSIONS:
            if extension in DISABLED_COGS:
                print(f"Extension {extension} disabled (DISABLED_COGS), not loaded")
                continue
            await self.load_extension(extension)

        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)

        logger = self.get_cog("Logger")
        if logger:
            await logger.send_log(
                level="DEBUG",
                event="SYSTEM_STARTUP",
                info=(
                    f"**Name:** ClepshydraBotte\n"
                    f"**Version:** {VERSION}\n"
                    f"**Status:** Online and operational\n"
                    f"**Database:** Initialized\n"
                    f"**Commands synced:** {len(synced)}\n"
                    f"**Library version:** {discord.__version__}"
                ),
            )

            # Status summary for the log channel ONLY (not community): the
            # latest Event Schedule/Banned and Restricted page the bot ALREADY
            # knows, read from the state files on disk with no network request.
            # Distinct from the real periodic check (which queries the sitemap
            # shortly after, once the create_task calls below start) - this only
            # shows what the bot already knows at each restart, handy to verify
            # at a glance that the saved state is the expected one.
            event_schedule_state = get_latest_known_event_schedule()
            ban_announcement_state = get_latest_known_ban_announcement()
            await logger.send_log(
                level="INFO",
                event="STARTUP_STATUS",
                info=(
                    f"**Latest known Event Schedule page:** "
                    f"{event_schedule_state['url'] or 'none (empty state)'}\n"
                    f"**Latest known Banned and Restricted Announcement:** "
                    f"{ban_announcement_state['url'] or 'none (empty state)'}"
                ),
            )

        # Started AFTER the startup logs: create_task only schedules, it doesn't
        # run right away, but the tasks' first runs (SPG/Event Schedule checks,
        # both HTTP and not instant) can still finish before the await on
        # tree.sync() above if they start before it - observed in production,
        # the SYSTEM_STARTUP log arrived after the automatic check logs instead
        # of before.
        self.loop.create_task(periodic_save_loop())
        self.loop.create_task(periodic_spg_refresh_loop(self))
        self.loop.create_task(periodic_event_schedule_check_loop(self))
        self.loop.create_task(periodic_ban_announcement_check_loop(self))

    async def close(self):
        # Save card cache changes the 60s loop hasn't persisted yet (e.g. on a
        # `pm2 restart`) before closing the DB. A failure here must not block
        # shutdown.
        try:
            await save_cache()
        except Exception as e:
            print(f"Saving the card cache on shutdown failed: {e}", file=sys.stderr)
        await close_db()
        await super().close()


def main() -> None:
    bot = ClepshydraBotte()
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("FATAL: invalid or expired Discord token. The bot cannot start.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"FATAL: bot startup failed: {e}", file=sys.stderr)
        sys.exit(1)


# Guarded so tests can import the extension list without starting the bot; pm2 runs `python main.py`.
if __name__ == "__main__":
    main()
