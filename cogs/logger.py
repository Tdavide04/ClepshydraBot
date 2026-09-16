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
        """Metodo universale per inviare log con pattern specifico.

        fields: lista opzionale di dict {"name", "value", "inline"} aggiunti
        come campi embed separati (nome in grassetto/risalto, distinto dal
        corpo della description) invece che infilati come altro testo nella
        description - usato per contenuti a sezioni dove il solo grassetto
        markdown in un paragrafo unico risultava poco leggibile.

        files: lista opzionale di discord.File allegati allo stesso messaggio
        dell'embed - usata dal calendario eventi Arena
        (utils/arena_event_schedule.py) per allegare le immagini calendario
        generate invece di descrivere gli eventi solo a parole.

        extra_channel_id: se impostato (e diverso da 0/None), lo stesso
        aggiornamento viene postato anche in questo canale oltre al canale
        log - usato dal monitor Banned and Restricted e dal monitor Event
        Schedule per rendere pubblico un aggiornamento che riguarda tutta la
        community, non solo lo staff. NON riusa l'embed del canale log: quel
        titolo/description contengono dettagli da staff ("Controllo manuale
        forzato", l'utente che ha invocato il comando, il livello/nome
        evento tecnico) che non hanno senso in un canale pubblico dove si fa
        anche @everyone. Viene invece costruito un embed indipendente da
        `community_title`/`community_info` (stesso colore, stessi `fields` e
        `files` - quei due sono contenuto genuino anche per la community,
        solo la cornice cambia). Un discord.File e' uno stream single-use:
        prima del secondo invio viene richiamato `File.reset()` su ciascuno
        (riporta il cursore del file a 0) per poterli ri-allegare senza
        dover ricreare gli oggetti.

        community_title / community_info: titolo e testo dedicati
        all'embed pubblico, usati solo se `extra_channel_id` e' impostato.
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
                    print(f"⚠️ Errore logger (canale extra): {e}")

        except Exception as e:
            print(f"⚠️ Errore logger: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Esempio di log INFO al nuovo ingresso."""
        role = discord.utils.get(member.guild.roles, name="Viandante")
        status = "❌ Ruolo non trovato"
        
        if role:
            try:
                await member.add_roles(role)
                status = "✅ Ruolo 'Viandante' assegnato"
                level = "INFO"
            except discord.Forbidden:
                status = "⚠️ Errore permessi"
                level = "ERROR"
        else:
            level = "WARN"

        await self.send_log(
            level=level,
            event="MEMBER_JOIN",
            user=member,
            info=f"Nuovo ingresso nel server.\n**Stato:** {status}"
        )

async def setup(bot):
    await bot.add_cog(Logger(bot))