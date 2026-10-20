import discord
from discord.ext import commands
from datetime import datetime

from config.config import LOG_CHANNEL_ID

class Logger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log_channel_id = LOG_CHANNEL_ID
        
        self.levels = {
            "INFO": ("🟢", discord.Color.green()),
            "WARN": ("🟡", discord.Color.gold()),
            "ERROR": ("🔴", discord.Color.red()),
            "DEBUG": ("🔵", discord.Color.blue())
        }

    @staticmethod
    def _add_fields(embed, fields):
        for field in (fields or []):
            embed.add_field(
                name=field["name"],
                value=field["value"],
                inline=field.get("inline", False),
            )

    async def send_log(self, level, event, user=None, channel=None, info=None, fields=None, files=None,
                        extra_channel_id=None, community_title=None, community_info=None):
        """Single entry point for posting a log embed to the log channel.

        fields: optional list of {"name", "value", "inline"} dicts, added as
        separate embed fields (name highlighted, distinct from the
        description body) instead of being stuffed into the description as
        more text - used for sectioned content where markdown bold alone in a
        single paragraph read poorly.

        files: optional list of discord.File attached to the same message as
        the embed - used by the Arena event calendar
        (utils/arena_event_schedule.py) to attach the generated calendar
        images instead of describing events in words only.

        extra_channel_id: if set (and not 0/None), the same update is also
        posted to this channel besides the log channel - used by the Banned
        and Restricted and Event Schedule monitors to make public an update
        that concerns the whole community, not just staff. It does NOT reuse
        the log-channel embed: that title/description carry staff detail
        ("Forced manual check", the user who invoked the command, the
        technical level/event name) that makes no sense in a public channel
        where @everyone gets pinged. A separate embed is built from
        `community_title`/`community_info` instead (same color, same `fields`
        and `files` - those two are genuine content for the community too,
        only the frame changes). A discord.File is a single-use stream:
        before the second send, `File.reset()` is called on each one (it
        rewinds the file cursor to 0) so they can be attached again without
        recreating the objects.

        community_title / community_info: title and text for the public
        embed, used only if `extra_channel_id` is set (written in Italian,
        since the community reads them).
        """
        emoji, color = self.levels.get(level.upper(), self.levels["INFO"])

        try:
            log_channel = await self.bot.fetch_channel(self.log_channel_id)

            description = ""
            if user:
                description += f"**User:** {user.mention} ({user.name})\n"
            if channel:
                description += f"**Channel:** {channel.mention if hasattr(channel, 'mention') else channel}\n"
            if info:
                if info.strip().startswith("**"):
                    description += f"{info}\n"
                else:
                    description += f"**Info:** {info}\n"

            embed = discord.Embed(
                title=f"{emoji} [{level.upper()}] | {event.upper()}",
                description=description.strip(),
                color=color,
                timestamp=datetime.now()
            )
            self._add_fields(embed, fields)
            embed.set_footer(text=f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            await log_channel.send(embed=embed, files=files or None)

            if extra_channel_id:
                try:
                    for f in (files or []):
                        f.reset()

                    community_embed = discord.Embed(
                        title=community_title or event.replace("_", " ").title(),
                        description=community_info or "",
                        color=color,
                    )
                    self._add_fields(community_embed, fields)

                    extra_channel = await self.bot.fetch_channel(extra_channel_id)
                    await extra_channel.send(embed=community_embed, files=files or None)
                except Exception as e:
                    print(f"⚠️ Logger error (extra channel): {e}")

        except Exception as e:
            print(f"⚠️ Logger error: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Assigns the initial role to a new member and logs the join."""
        role = discord.utils.get(member.guild.roles, name="Viandante")
        status = "❌ Role not found"
        
        if role:
            try:
                await member.add_roles(role)
                status = "✅ Role 'Viandante' assigned"
                level = "INFO"
            except discord.Forbidden:
                status = "⚠️ Missing permissions"
                level = "ERROR"
        else:
            level = "WARN"

        await self.send_log(
            level=level,
            event="MEMBER_JOIN",
            user=member,
            info=f"New member joined the server.\n**Status:** {status}"
        )

async def setup(bot):
    await bot.add_cog(Logger(bot))