import discord
from discord.ext import commands
from datetime import datetime

from services.tournament_service import TournamentService
from utils.permissions import is_admin
from utils.tournament_embeds import (
    build_standings_embed,
    build_pairings_embed,
    build_start_embed,
)
from database.models import Tournament, TournamentStatus, TournamentPlayer, MatchResult
from database import get_session
from repositories.banlist_repository import BanlistRepository
from cogs.deck_validation.service import ArtisanService
from cogs.deck_validation.validators import parse_decklist, validate_counts
from config.config import GUILD_ID, TOURNAMENT_CHANNEL_ID, PUBLIC_DECK_CHANNEL_ID


class CreaTorneoModal(discord.ui.Modal, title="Crea Nuovo Torneo"):
    def __init__(self, service: TournamentService, bot):
        super().__init__()
        self.service = service
        self.bot = bot

    nome = discord.ui.TextInput(
        label="Nome del torneo",
        placeholder="es. Artisan #1 - Luglio 2025",
        required=True,
        max_length=100,
    )
    formato = discord.ui.TextInput(
        label="Formato",
        placeholder="Artisan",
        default="Artisan",
        required=True,
        max_length=50,
    )
    max_partecipanti = discord.ui.TextInput(
        label="Max partecipanti (opzionale)",
        placeholder="Lascia vuoto per nessun limite",
        required=False,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        nome_val = self.nome.value.strip()
        formato_val = self.formato.value.strip() or "Artisan"
        max_raw = self.max_partecipanti.value.strip()

        max_players = None
        if max_raw:
            try:
                max_players = int(max_raw)
                if max_players < 2:
                    return await interaction.response.send_message(
                        "Il numero massimo di partecipanti deve essere almeno 2.", ephemeral=True
                    )
            except ValueError:
                return await interaction.response.send_message(
                    "Inserisci un numero valido per i partecipanti.", ephemeral=True
                )

        tournament = await self.service.create_tournament(
            name=nome_val, format=formato_val, max_players=max_players
        )

        embed = discord.Embed(
            title="\U0001F195 Nuovo Torneo",
            color=discord.Color.green(),
            timestamp=datetime.now(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Nome", value=f"**{tournament.name}**", inline=True)
        embed.add_field(name="ID", value=f"`{tournament.id}`", inline=True)
        embed.add_field(name="Formato", value=tournament.format, inline=True)
        if max_players:
            embed.add_field(name="Max Partecipanti", value=str(max_players), inline=True)
        embed.add_field(name="Stato", value="Iscrizioni aperte", inline=True)
        embed.set_footer(
            text=f"Creato da {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.send_log(
                level="INFO",
                event="TOURNAMENT_CREATED",
                user=interaction.user,
                info=f"Torneo **{tournament.name}** (ID: {tournament.id}) creato."
            )


class IscrivitiModal(discord.ui.Modal, title="Iscrizione Torneo - Inserisci il tuo mazzo"):
    def __init__(
        self,
        torneo_id: int,
        torneo_name: str,
        service: TournamentService,
        artisan_service: ArtisanService,
        bot,
    ):
        super().__init__()
        self.torneo_id = torneo_id
        self.torneo_name = torneo_name
        self.service = service
        self.artisan_service = artisan_service
        self.bot = bot

    titolo = discord.ui.TextInput(
        label="Nome del tuo mazzo",
        placeholder="es. Mono Red Aggro",
        required=True,
        max_length=100,
    )

    deck_list = discord.ui.TextInput(
        label="Lista del tuo mazzo Artisan",
        style=discord.TextStyle.paragraph,
        placeholder="4 Experimental Confectioner / 3 Honey Mammoth ...",
        required=True,
        min_length=10,
        max_length=2000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        deck_name = self.titolo.value.strip() or "ARTISAN DECK"
        entries, total_cards, _ = parse_decklist(self.deck_list.value)

        if not interaction.response.is_done():
            try:
                await interaction.response.defer()
            except (discord.NotFound, discord.HTTPException):
                pass

        result = await self.artisan_service.validate_deck(
            entries, deck_name, total_cards
        )

        deck_image = await self.artisan_service.generate_deck_image(
            result, interaction.user.display_name
        )

        logger = self.bot.get_cog("Logger")

        if not result.is_valid:
            embed = discord.Embed(
                title="\u274c Mazzo non valido",
                description=f"La registrazione a **{self.torneo_name}** \u00e8 stata rifiutata.",
                color=discord.Color.red(),
            )

            errors = []
            if result.main_count < 60 or result.side_count > 15:
                errors = validate_counts(result.main_count, result.side_count)

            if result.banned_cards:
                embed.add_field(
                    name="Carte bannate",
                    value="\n".join(f"\u2022 {c}" for c in result.banned_cards[:10]),
                    inline=False,
                )
            if result.illegal_rarity_cards:
                embed.add_field(
                    name="Non legali in Artisan Arena",
                    value="\n".join(f"\u2022 {c}" for c in result.illegal_rarity_cards[:10]),
                    inline=False,
                )
            if result.invalid_cards:
                embed.add_field(
                    name="Carte non trovate",
                    value="\n".join(f"\u2022 {c}" for c in result.invalid_cards[:10]),
                    inline=False,
                )
            if errors:
                embed.add_field(
                    name="Errori conteggio",
                    value="\n".join(f"\u2022 {e}" for e in errors),
                    inline=False,
                )

            embed.set_footer(text=f"Torneo ID: {self.torneo_id}")

            kwargs = {"embed": embed}
            if deck_image:
                deck_image.seek(0)
                kwargs["file"] = discord.File(deck_image, filename="deck.png")
                embed.set_image(url="attachment://deck.png")

            await interaction.followup.send(**kwargs)

            if logger:
                await logger.send_log(
                    level="WARN",
                    event="TOURNAMENT_DECK_CHECK",
                    user=interaction.user,
                    info=(
                        f"Esito: NON VALIDO (registrazione rifiutata)\n"
                        f"Torneo: **{self.torneo_name}** (ID: {self.torneo_id})\n"
                        f"Mazzo: **{deck_name}**\n"
                        f"Carte: {result.total_cards} ({result.main_count}M + {result.side_count}S)\n"
                        f"Bannate: {len(result.banned_cards)} | "
                        f"Illegali: {len(result.illegal_rarity_cards)} | "
                        f"Non trovate: {len(result.invalid_cards)}"
                    ),
                )
            return

        msg = await self.service.register_player(
            self.torneo_id, interaction.user.id, deck_name
        )

        embed = discord.Embed(
            title="\u2705 Iscrizione confermata",
            description=msg,
            color=discord.Color.green(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="Giocatore", value=interaction.user.mention, inline=True)
        embed.add_field(name="Mazzo", value=f"**{deck_name}**", inline=True)
        embed.add_field(name="Carte", value=f"{total_cards} ({result.main_count}M + {result.side_count}S)", inline=True)
        embed.set_footer(text=f"Torneo ID: {self.torneo_id}")

        kwargs = {"embed": embed}
        if deck_image:
            deck_image.seek(0)
            kwargs["file"] = discord.File(deck_image, filename="deck.png")
            embed.set_image(url="attachment://deck.png")

        await interaction.followup.send(**kwargs)

        deck_channel = self.bot.get_channel(PUBLIC_DECK_CHANNEL_ID) if PUBLIC_DECK_CHANNEL_ID else None
        if deck_channel:
            deck_text = self.deck_list.value.strip()
            deck_embed = discord.Embed(
                title=f"Deck di {interaction.user.display_name}",
                description=f"```{deck_text}```",
                color=discord.Color.blue(),
                timestamp=datetime.now(),
            )
            deck_embed.set_author(
                name=interaction.user.display_name,
                icon_url=interaction.user.display_avatar.url,
            )
            deck_embed.add_field(name="Torneo", value=f"**{self.torneo_name}**", inline=True)
            deck_embed.add_field(name="Mazzo", value=f"**{deck_name}**", inline=True)
            deck_embed.set_footer(text=f"Torneo ID: {self.torneo_id}")
            try:
                await deck_channel.send(embed=deck_embed)
            except discord.HTTPException:
                pass

        if logger:
            await logger.send_log(
                level="INFO",
                event="TOURNAMENT_DECK_CHECK",
                user=interaction.user,
                info=(
                    f"Esito: OK (registrato al torneo)\n"
                    f"Torneo: **{self.torneo_name}** (ID: {self.torneo_id})\n"
                    f"Mazzo: **{deck_name}**\n"
                    f"Carte: {result.total_cards} ({result.main_count}M + {result.side_count}S)"
                ),
            )
            await logger.send_log(
                level="INFO",
                event="REGISTRATION_CONFIRMED",
                user=interaction.user,
                info=(
                    f"Torneo **{self.torneo_name}** (ID: {self.torneo_id}) \u2014 "
                    f"Mazzo: **{deck_name}** ({result.main_count}M + {result.side_count}S)"
                ),
            )


class RisultatoView(discord.ui.View):
    def __init__(
        self, match, tournament, service,
        my_tp, opponent_tp, bot,
    ):
        super().__init__()
        self.match = match
        self.tournament = tournament
        self.service = service
        self.my_tp = my_tp
        self.opponent_tp = opponent_tp
        self.bot = bot
        self.selected = None

    @discord.ui.select(
        placeholder="Seleziona risultato...",
        options=[
            discord.SelectOption(
                label="Vittoria 2-0", value="win_20",
                emoji="\u2705", description="Hai vinto 2-0 (3 punti)",
            ),
            discord.SelectOption(
                label="Vittoria 2-1", value="win_21",
                emoji="\u2705", description="Hai vinto 2-1 (3 punti)",
            ),
            discord.SelectOption(
                label="Pareggio", value="draw",
                emoji="\U0001f91d", description="Avete pareggiato (1 punto)",
            ),
            discord.SelectOption(
                label="Sconfitta 1-2", value="loss_12",
                emoji="\u274c", description="Hai perso 1-2 (0 punti)",
            ),
            discord.SelectOption(
                label="Sconfitta 0-2", value="loss_02",
                emoji="\u274c", description="Hai perso 0-2 (0 punti)",
            ),
        ],
    )
    async def result_select(
        self, interaction: discord.Interaction,
        select: discord.ui.Select,
    ):
        self.selected = select.values[0]
        select.disabled = True

        labels = {
            "win_20": "\u2705 Vittoria 2-0", "win_21": "\u2705 Vittoria 2-1",
            "draw": "\U0001f91d Pareggio",
            "loss_12": "\u274c Sconfitta 1-2", "loss_02": "\u274c Sconfitta 0-2",
        }
        await interaction.response.edit_message(
            content=f"Risultato selezionato: **{labels.get(self.selected, self.selected)}**",
            view=self,
        )

    @discord.ui.button(label="Conferma", style=discord.ButtonStyle.green)
    async def confirm(
        self, interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if self.selected is None:
            return await interaction.response.send_message(
                "Seleziona prima un risultato.", ephemeral=True
            )

        score_map = {
            "win_20": (2, 0),
            "win_21": (2, 1),
            "draw": (None, None),
            "loss_12": (1, 2),
            "loss_02": (0, 2),
        }

        p1_gw, p2_gw = score_map.get(self.selected, (None, None))

        if self.selected in ("win_20", "win_21"):
            winner_id = self.my_tp.id if self.my_tp else None
            result = "win"
        elif self.selected in ("loss_12", "loss_02"):
            winner_id = self.opponent_tp.id if self.opponent_tp else None
            result = "win"
        else:
            winner_id = None
            result = "draw"

        if self.my_tp and self.match.player1_id == self.my_tp.id:
            p1_game_wins, p2_game_wins = p1_gw, p2_gw
        else:
            p1_game_wins, p2_game_wins = p2_gw, p1_gw

        msg = await self.service.submit_result(
            self.match.id, winner_id, result,
            p1_game_wins=p1_game_wins, p2_game_wins=p2_game_wins,
        )

        labels = {
            "win_20": "\u2705 Vittoria 2-0", "win_21": "\u2705 Vittoria 2-1",
            "draw": "\U0001f91d Pareggio",
            "loss_12": "\u274c Sconfitta 1-2", "loss_02": "\u274c Sconfitta 0-2",
        }
        embed = discord.Embed(
            title="\U0001f4dd Risultato Partita",
            description=(
                f"{interaction.user.mention} ha registrato il risultato del "
                f"**Tavolo {self.match.table_number}** "
                f"(Round {self.match.round_number})"
            ),
            color=discord.Color.green() if "Registrato" in msg else discord.Color.orange(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="Risultato", value=labels.get(self.selected, self.selected), inline=True)
        embed.add_field(name="Torneo", value=self.tournament.name, inline=True)
        embed.set_footer(text=f"Match ID: {self.match.id}")

        await interaction.response.edit_message(
            content=None, embed=embed, view=None,
        )

        channel = interaction.channel
        if channel:
            await channel.send(
                f"{interaction.user.mention} \U0001f4dd Risultato **Tavolo {self.match.table_number}**: "
                f"{labels.get(self.selected, self.selected)}"
            )

        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.send_log(
                level="INFO" if "Registrato" in msg else "WARN",
                event="MATCH_RESULT",
                user=interaction.user,
                info=f"Match {self.match.id}: {msg}",
            )

        self.stop()

    @discord.ui.button(label="Annulla", style=discord.ButtonStyle.grey)
    async def cancel(
        self, interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="Inserimento annullato.", view=self,
        )
        self.stop()


class TournamentSystemCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.service = TournamentService(bot)
        self.artisan_service = ArtisanService(bot)

    async def _log(self, level, event, user=None, info=None):
        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.send_log(level=level, event=event, user=user, info=info)

    async def _resolve_tournament(
        self, torneo: str | None = None, torneo_id: int | None = None
    ) -> Tournament | None:
        if torneo is not None:
            return await self.service.find_tournament(torneo)
        if torneo_id is not None:
            return await self.service.get_tournament(torneo_id)
        return await self.service.get_latest_tournament()

    async def _check_tournament_channel(
        self, interaction: discord.Interaction
    ) -> bool:
        if TOURNAMENT_CHANNEL_ID and interaction.channel_id != TOURNAMENT_CHANNEL_ID:
            await interaction.response.send_message(
                "Questo comando pu\u00f2 essere utilizzato solo nel canale dedicato ai tornei.",
                ephemeral=True,
            )
            return False
        return True

    def _player_display(self, tp: TournamentPlayer | None) -> str:
        if tp is None:
            return "*Sconosciuto*"
        name = f"Giocatore #{tp.id}"
        deck = f" ({tp.deck_name})" if tp.deck_name else ""
        if tp.user and self.bot:
            guild = self.bot.get_guild(GUILD_ID)
            if guild:
                member = guild.get_member(tp.user.discord_id)
                if member:
                    name = member.display_name
        return f"**{name}**{deck}"

    def _resolve_name(self, tp: TournamentPlayer | None) -> str:
        if tp is None:
            return "*Sconosciuto*"
        name = f"Giocatore #{tp.id}"
        if tp.user and self.bot:
            guild = self.bot.get_guild(GUILD_ID)
            if guild:
                member = guild.get_member(tp.user.discord_id)
                if member:
                    name = member.display_name
        return name

    # ------------------------------------------------------------------
    # Comandi Admin
    # ------------------------------------------------------------------

    @discord.app_commands.command(
        name="crea_torneo",
        description="Crea un nuovo torneo"
    )
    @is_admin()
    async def crea_torneo(self, interaction: discord.Interaction):
        if not await self._check_tournament_channel(interaction):
            return
        modal = CreaTorneoModal(self.service, self.bot)
        await interaction.response.send_modal(modal)

    @discord.app_commands.command(
        name="avvia_torneo",
        description="Avvia un torneo in attesa di iscrizioni"
    )
    @is_admin()
    @discord.app_commands.describe(
        torneo="ID o nome del torneo da avviare (opzionale, usa l'ultimo)"
    )
    async def avvia_torneo(
        self,
        interaction: discord.Interaction,
        torneo: str | None = None,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=False)

        tournament = await self._resolve_tournament(torneo=torneo)
        if tournament is None:
            return await interaction.followup.send(
                "Nessun torneo in fase di iscrizioni." if torneo is None
                else f"Torneo `{torneo}` non trovato.",
                ephemeral=True,
            )
        if tournament.status != TournamentStatus.REGISTRATION:
            return await interaction.followup.send(
                "Il torneo non \u00e8 in fase di iscrizioni.", ephemeral=True
            )

        msg = await self.service.start_tournament(tournament.id)

        if "non trovato" in msg or "non e attivo" in msg or "Servono almeno" in msg:
            return await interaction.followup.send(msg, ephemeral=True)

        players = await self.service.get_registered_players(tournament.id)
        player_data = [
            (self._resolve_name(p), p.deck_name or "")
            for p in players
        ]

        embed_players = build_start_embed(
            tournament_name=tournament.name,
            tournament_id=tournament.id,
            players=player_data,
            round_count=tournament.round_count or 0,
        )
        await interaction.followup.send(embed=embed_players)

        matches = await self.service.get_matches(tournament.id)
        round1 = [m for m in matches if m.round_number == 1]
        if round1:
            pairings = []
            for m in round1:
                p1_name = self._resolve_name(m.player1) if m.player1 else f"Giocatore #{m.player1_id}"
                p1_deck = m.player1.deck_name if m.player1 else None
                if m.player2_id is not None:
                    p2_name = (
                        self._resolve_name(m.player2)
                        if m.player2
                        else f"Giocatore #{m.player2_id}"
                    )
                    p2_deck = m.player2.deck_name if m.player2 else None
                else:
                    p2_name = None
                    p2_deck = None
                pairings.append({
                    "table": m.table_number,
                    "player1": p1_name,
                    "player1_deck": p1_deck,
                    "player2": p2_name,
                    "player2_deck": p2_deck,
                })

            embed_pairings = build_pairings_embed(
                tournament_name=tournament.name,
                tournament_id=tournament.id,
                round_number=1,
                pairings=pairings,
            )
            await interaction.followup.send(embed=embed_pairings)

        await self._log(
            "INFO", "TOURNAMENT_STARTED", user=interaction.user,
            info=msg
        )

    @discord.app_commands.command(
        name="drop_giocatore",
        description="Rimuovi forzatamente un giocatore dal torneo attivo"
    )
    @is_admin()
    @discord.app_commands.describe(
        giocatore="Giocatore da rimuovere",
        torneo="ID o nome del torneo (opzionale, usa l'ultimo)",
    )
    async def drop_giocatore(
        self,
        interaction: discord.Interaction,
        giocatore: discord.User,
        torneo: str | None = None,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=False)

        tournament = await self._resolve_tournament(torneo=torneo)
        if tournament is None:
            return await interaction.followup.send(
                "Nessun torneo attivo." if torneo is None
                else f"Torneo `{torneo}` non trovato.",
                ephemeral=True,
            )

        msg = await self.service.force_drop_player(
            tournament.id, giocatore.id
        )

        if "non trovato" in msg or "non e attivo" in msg or "non iscritto" in msg:
            return await interaction.followup.send(msg, ephemeral=True)

        embed = discord.Embed(
            title="\u274c Giocatore Rimosso",
            description=msg,
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )
        embed.set_footer(text=f"Torneo ID: {tournament.id}")
        await interaction.followup.send(embed=embed)

        await self._log(
            "INFO", "PLAYER_DROPPED", user=interaction.user,
            info=(
                f"Giocatore {giocatore.mention} rimosso dal torneo "
                f"**{tournament.name}** (ID: {tournament.id})."
            ),
        )

    @discord.app_commands.command(
        name="concludi_torneo",
        description="Concludi forzatamente un torneo attivo"
    )
    @is_admin()
    @discord.app_commands.describe(
        torneo="ID o nome del torneo da concludere (opzionale, usa l'ultimo)",
    )
    async def concludi_torneo(
        self,
        interaction: discord.Interaction,
        torneo: str | None = None,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=False)

        tournament = await self._resolve_tournament(torneo=torneo)
        if tournament is None:
            return await interaction.followup.send(
                "Nessun torneo attivo." if torneo is None
                else f"Torneo `{torneo}` non trovato.",
                ephemeral=True,
            )

        msg = await self.service.force_conclude_tournament(tournament.id)

        if "non trovato" in msg or "non e attivo" in msg:
            return await interaction.followup.send(msg, ephemeral=True)

        embed = discord.Embed(
            title="\U0001f3f4 Torneo Concluso",
            description=msg,
            color=discord.Color.dark_red(),
            timestamp=datetime.now(),
        )
        embed.set_footer(text=f"Torneo ID: {tournament.id}")
        await interaction.followup.send(embed=embed)

        await self._log(
            "INFO", "TOURNAMENT_CONCLUDED", user=interaction.user,
            info=(
                f"Torneo **{tournament.name}** (ID: {tournament.id}) "
                f"concluso forzatamente."
            ),
        )

    @discord.app_commands.command(
        name="torneo_next_turn",
        description="Genera il prossimo turno del torneo attivo"
    )
    @is_admin()
    @discord.app_commands.describe(
        torneo="ID o nome del torneo (opzionale, usa l'ultimo)"
    )
    async def torneo_next_turn(
        self,
        interaction: discord.Interaction,
        torneo: str | None = None,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=False)

        tournament = await self._resolve_tournament(torneo=torneo)
        if tournament is None:
            return await interaction.followup.send(
                "Nessun torneo attivo." if torneo is None
                else f"Torneo `{torneo}` non trovato.",
                ephemeral=True,
            )
        if tournament.status != TournamentStatus.ACTIVE:
            return await interaction.followup.send(
                "Il torneo non \u00e8 attivo.", ephemeral=True
            )

        msg = await self.service.generate_next_round(tournament.id)

        if "non trovato" in msg or "non e attivo" in msg:
            return await interaction.followup.send(msg, ephemeral=True)

        if "ancora" in msg and "senza risultato" in msg:
            embed = discord.Embed(
                title="\u23f3 Partite in sospeso",
                description=msg,
                color=discord.Color.orange(),
                timestamp=datetime.now(),
            )
            embed.set_footer(text=f"Torneo ID: {tournament.id}")
            await interaction.followup.send(embed=embed)
            return

        if "completato" in msg:
            embed = discord.Embed(
                title="\U0001f3c6 Torneo Completato!",
                description=msg,
                color=discord.Color.gold(),
                timestamp=datetime.now(),
            )
            embed.set_footer(text=f"Torneo ID: {tournament.id}")
            await interaction.followup.send(embed=embed)

            await self._log(
                "INFO", "TOURNAMENT_COMPLETED", user=interaction.user,
                info=f"Torneo **{tournament.name}** (ID: {tournament.id}) completato."
            )
            return

        current_round = await self.service.get_current_round(tournament.id)
        embed = discord.Embed(
            title=f"\U0001f504 Round {current_round} Generato",
            description=msg,
            color=discord.Color.teal(),
            timestamp=datetime.now(),
        )
        embed.set_footer(text=f"Torneo ID: {tournament.id}")
        await interaction.followup.send(embed=embed)

        matches = await self.service.get_matches(tournament.id)
        round_matches = [m for m in matches if m.round_number == current_round]
        if round_matches:
            pairings = []
            for m in round_matches:
                p1_name = self._resolve_name(m.player1) if m.player1 else f"Giocatore #{m.player1_id}"
                p1_deck = m.player1.deck_name if m.player1 else None
                if m.player2_id is not None:
                    p2_name = (
                        self._resolve_name(m.player2)
                        if m.player2
                        else f"Giocatore #{m.player2_id}"
                    )
                    p2_deck = m.player2.deck_name if m.player2 else None
                else:
                    p2_name = None
                    p2_deck = None
                pairings.append({
                    "table": m.table_number,
                    "player1": p1_name,
                    "player1_deck": p1_deck,
                    "player2": p2_name,
                    "player2_deck": p2_deck,
                })

            pairings_embed = build_pairings_embed(
                tournament_name=tournament.name,
                tournament_id=tournament.id,
                round_number=current_round,
                pairings=pairings,
            )
            await interaction.followup.send(embed=pairings_embed)

        await self._log(
            "INFO", "ROUND_GENERATED", user=interaction.user,
            info=f"Torneo **{tournament.name}** (ID: {tournament.id}) \u2014 Round {current_round}: {msg}"
        )

    # ------------------------------------------------------------------
    # Comandi Giocatori
    # ------------------------------------------------------------------

    @discord.app_commands.command(
        name="lista_tornei",
        description="Mostra tutti i tornei con ID, nome, partecipanti e stato"
    )
    async def lista_tornei(self, interaction: discord.Interaction):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=False)

        tournaments = await self.service.list_tournaments_with_counts()

        if not tournaments:
            await interaction.followup.send("Nessun torneo trovato.")
            return

        embed = discord.Embed(
            title="\U0001f3c6 Lista Tornei",
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )

        status_emoji = {
            "registration": "\U0001f4c5",
            "active": "\U0001f525",
            "completed": "\U00002705",
        }
        status_label = {
            "registration": "Iscrizioni aperte",
            "active": "In corso",
            "completed": "Completato",
        }

        for tournament, player_count in tournaments:
            icon = status_emoji.get(tournament.status.value, "\U00002753")
            stato = status_label.get(tournament.status.value, tournament.status.value.capitalize())

            players = f"{player_count}"
            if tournament.max_players:
                players += f"/{tournament.max_players}"

            embed.add_field(
                name=f"`#{tournament.id}` {tournament.name}",
                value=f"{icon} {stato} \u2022 \U0001f465 {players}",
                inline=False,
            )

        embed.set_footer(text=f"Totale tornei: {len(tournaments)}")
        await interaction.followup.send(embed=embed)

    @discord.app_commands.command(
        name="iscriviti",
        description="Iscriviti a un torneo"
    )
    @discord.app_commands.describe(
        torneo_id="ID del torneo (opzionale, usa l'ultimo)"
    )
    async def iscriviti(
        self,
        interaction: discord.Interaction,
        torneo_id: int | None = None,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        tournament = await self._resolve_tournament(torneo_id=torneo_id)
        if tournament is None:
            return await interaction.response.send_message(
                "Nessun torneo in fase di iscrizioni." if torneo_id is None
                else "Torneo non trovato.",
                ephemeral=True,
            )
        if tournament.status != TournamentStatus.REGISTRATION:
            return await interaction.response.send_message(
                "Il torneo non accetta iscrizioni.", ephemeral=True
            )

        already = await self.service.is_player_registered(
            tournament.id, interaction.user.id
        )
        if already:
            return await interaction.response.send_message(
                "Sei gi\u00e0 iscritto a questo torneo.", ephemeral=True
            )

        modal = IscrivitiModal(
            tournament.id, tournament.name, self.service, self.artisan_service, self.bot
        )
        await interaction.response.send_modal(modal)

    @discord.app_commands.command(
        name="left_torneo",
        description="Esci da un torneo prima che inizi"
    )
    @discord.app_commands.describe(
        torneo_id="ID del torneo da cui uscire (opzionale, usa l'ultimo)"
    )
    async def left_torneo(
        self,
        interaction: discord.Interaction,
        torneo_id: int | None = None,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=False)

        tournament = await self._resolve_tournament(torneo_id=torneo_id)
        if tournament is None:
            return await interaction.followup.send(
                "Nessun torneo disponibile." if torneo_id is None
                else "Torneo non trovato.",
                ephemeral=True,
            )
        if tournament.status != TournamentStatus.REGISTRATION:
            return await interaction.followup.send(
                "Non puoi uscire da un torneo gi\u00e0 iniziato o completato.", ephemeral=True
            )

        msg = await self.service.unregister_player(tournament.id, interaction.user.id)
        if "Non sei iscritto" in msg or "Torneo non trovato" in msg:
            return await interaction.followup.send(msg, ephemeral=True)

        embed = discord.Embed(
            title="\U0001f6aa Uscita dal torneo",
            description=f"{interaction.user.mention} \u00e8 uscito dal torneo **{tournament.name}**.",
            color=discord.Color.orange(),
            timestamp=datetime.now(),
        )
        embed.set_footer(text=f"Torneo ID: {tournament.id}")
        await interaction.followup.send(embed=embed)

    @discord.app_commands.command(
        name="risultato",
        description="Inserisci il risultato di una partita"
    )
    @discord.app_commands.describe(
        torneo="ID o nome del torneo (opzionale, usa l'ultimo)",
    )
    async def risultato(
        self,
        interaction: discord.Interaction,
        torneo: str | None = None,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        if torneo:
            tournament = await self.service.find_tournament(torneo)
            if tournament is None or tournament.status != TournamentStatus.ACTIVE:
                return await interaction.followup.send(
                    f"Torneo `{torneo}` non trovato o non attivo.", ephemeral=True
                )
            candidates = [tournament]
        else:
            latest = await self.service.get_latest_tournament()
            if latest is None or latest.status != TournamentStatus.ACTIVE:
                return await interaction.followup.send("Nessun torneo attivo.", ephemeral=True)
            candidates = [latest]

        match = None
        chosen_tournament = None
        for t in candidates:
            m = await self.service.find_pending_match_for_user(
                t.id, interaction.user.id
            )
            if m is not None:
                match = m
                chosen_tournament = t
                break

        if match is None:
            return await interaction.followup.send(
                "Nessuna partita in sospeso trovata per te.", ephemeral=True
            )

        embed = discord.Embed(
            title=f"\U0001f3b2 Risultato \u2014 {chosen_tournament.name}",
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )

        tp1 = match.player1
        tp2 = match.player2
        p1 = self._player_display(tp1)
        p2 = self._player_display(tp2) if tp2 else "BYE"
        embed.add_field(
            name=f"Tavolo {match.table_number} \u2014 Round {match.round_number}",
            value=f"{p1} vs {p2}",
            inline=False,
        )

        def find_my_tp(tp1, tp2, discord_id):
            if tp1 and tp1.user and tp1.user.discord_id == discord_id:
                return tp1
            if tp2 and tp2.user and tp2.user.discord_id == discord_id:
                return tp2
            return None

        my_tp = find_my_tp(tp1, tp2, interaction.user.id)
        opponent_tp = tp2 if my_tp is tp1 else tp1

        view = RisultatoView(
            match, chosen_tournament, self.service,
            my_tp, opponent_tp, self.bot,
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.app_commands.command(
        name="classifica",
        description="Visualizza la classifica di un torneo"
    )
    @discord.app_commands.describe(
        torneo_id="ID del torneo (opzionale, usa il pi\u00f9 recente)"
    )
    async def classifica(
        self,
        interaction: discord.Interaction,
        torneo_id: int | None = None,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=False)

        if torneo_id is None:
            latest = await self.service.get_latest_tournament()
            if latest is None:
                return await interaction.followup.send(
                    "Nessun torneo disponibile.", ephemeral=True
                )
            torneo_id = latest.id

        result = await self.service.get_standings(torneo_id)
        if isinstance(result, str):
            return await interaction.followup.send(result, ephemeral=True)

        tournament = await self.service.get_tournament(torneo_id)
        if tournament is None:
            return await interaction.followup.send("Torneo non trovato.", ephemeral=True)

        round_number = await self.service.get_current_round(torneo_id)
        player_count = len(result)

        embed = build_standings_embed(
            tournament_name=tournament.name,
            tournament_id=torneo_id,
            round_number=round_number,
            entries=result,
            player_count=player_count,
        )
        await interaction.followup.send(embed=embed)

    async def _show_pairings(
        self,
        interaction: discord.Interaction,
        torneo_id: int | None = None,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=False)

        if torneo_id is None:
            latest = await self.service.get_latest_tournament()
            if latest is None:
                return await interaction.followup.send(
                    "Nessun torneo disponibile.", ephemeral=True
                )
            torneo_id = latest.id

        current_round = await self.service.get_current_round(torneo_id)
        if current_round == 0:
            return await interaction.followup.send(
                "Il torneo non \u00e8 ancora iniziato.", ephemeral=True
            )

        matches = await self.service.get_matches(torneo_id)
        round_matches = [m for m in matches if m.round_number == current_round]

        tournament = await self.service.get_tournament(torneo_id)
        tournament_name = tournament.name if tournament else f"Torneo #{torneo_id}"

        pairings = []
        for m in round_matches:
            p1_name = self._resolve_name(m.player1) if m.player1 else f"Giocatore #{m.player1_id}"
            p1_deck = m.player1.deck_name if m.player1 else None
            if m.player2_id is not None:
                p2_name = (
                    self._resolve_name(m.player2)
                    if m.player2
                    else f"Giocatore #{m.player2_id}"
                )
                p2_deck = m.player2.deck_name if m.player2 else None
            else:
                p2_name = None
                p2_deck = None
            pairings.append({
                "table": m.table_number,
                "player1": p1_name,
                "player1_deck": p1_deck,
                "player2": p2_name,
                "player2_deck": p2_deck,
            })

        embed = build_pairings_embed(
            tournament_name=tournament_name,
            tournament_id=torneo_id,
            round_number=current_round,
            pairings=pairings,
        )
        await interaction.followup.send(embed=embed)

    @discord.app_commands.command(
        name="turni",
        description="Visualizza gli accoppiamenti del turno corrente"
    )
    @discord.app_commands.describe(
        torneo_id="ID del torneo (opzionale, usa il pi\u00f9 recente)"
    )
    async def turni(
        self,
        interaction: discord.Interaction,
        torneo_id: int | None = None,
    ):
        await self._show_pairings(interaction, torneo_id)

    @discord.app_commands.command(
        name="leaderboard",
        description="Classifica rating giocatori (Glicko-2)"
    )
    @discord.app_commands.describe(
        limite="Numero di giocatori da mostrare (default 20)"
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        limite: int | None = None,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=False)

        limit = min(max(1, limite or 20), 100)

        entries = await self.service.get_leaderboard(limit)

        if not entries:
            await interaction.followup.send(
                "Nessun giocatore con rating disponibile. "
                "I rating vengono calcolati al termine dei tornei."
            )
            return

        embed = discord.Embed(
            title="\U0001f3c6 Leaderboard Rating",
            color=discord.Color.gold(),
            timestamp=datetime.now(),
        )

        lines = []
        MEDALS = ["\U0001f947", "\U0001f948", "\U0001f949"]
        for i, e in enumerate(entries):
            medal = MEDALS[i] if i < 3 else f"`#{i + 1:<2}`"
            confidence = f"\u00b1{e['rd']:.0f}" if e["rd"] < 100 else "\u00b1>100"
            lines.append(
                f"{medal} **{e['name']}** \u2014 "
                f"`{e['rating']:.0f}` {confidence} "
                f"({e['matches']} partite)"
            )

        chunks = [lines[i:i + 15] for i in range(0, len(lines), 15)]
        for i, chunk in enumerate(chunks):
            name = "Giocatori" if len(chunks) == 1 else f"Giocatori (parte {i + 1})"
            embed.add_field(name=name, value="\n".join(chunk), inline=False)

        embed.set_footer(text=f"Mostrati {len(entries)}/{limit} giocatori")
        await interaction.followup.send(embed=embed)

    @discord.app_commands.command(
        name="banlist",
        description="Visualizza le carte bannate"
    )
    async def banlist_lista(
        self,
        interaction: discord.Interaction,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=False)

        session = get_session()
        if session is None:
            return await interaction.followup.send("Database non disponibile.", ephemeral=True)

        try:
            repo = BanlistRepository(session)
            cards = await repo.get_all_for_format()
            if not cards:
                await interaction.followup.send("Nessuna carta bannata.", ephemeral=True)
                return
            sorted_cards = sorted(cards)
            embed = discord.Embed(
                title=f"\U0001f6ab Banlist ({len(sorted_cards)} carte)",
                color=discord.Color.red(),
                timestamp=datetime.now(),
            )
            chunks = [
                sorted_cards[i:i + 30]
                for i in range(0, len(sorted_cards), 30)
            ]
            for i, chunk in enumerate(chunks):
                name = "Carte" if len(chunks) == 1 else f"Carte (parte {i + 1})"
                embed.add_field(
                    name=name,
                    value="\n".join(f"\u2022 {c}" for c in chunk),
                    inline=False,
                )
            embed.set_footer(text="Formato: Artisan")
            await interaction.followup.send(embed=embed)
        finally:
            await session.close()

    @discord.app_commands.command(
        name="banlist_aggiungi",
        description="Aggiungi una carta alla banlist (admin)"
    )
    @is_admin()
    @discord.app_commands.describe(carta="Nome della carta da bannare")
    async def banlist_aggiungi(
        self,
        interaction: discord.Interaction,
        carta: str,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        session = get_session()
        if session is None:
            return await interaction.followup.send("Database non disponibile.", ephemeral=True)
        try:
            repo = BanlistRepository(session)
            await repo.add_card(carta)
            await self._log(
                "INFO", "BANLIST_ADD", user=interaction.user,
                info=f"Aggiunta: {carta}"
            )
            await interaction.followup.send(
                f"Carta **{carta}** aggiunta alla banlist.", ephemeral=True
            )
        finally:
            await session.close()

    @discord.app_commands.command(
        name="banlist_rimuovi",
        description="Rimuovi una carta dalla banlist (admin)"
    )
    @is_admin()
    @discord.app_commands.describe(carta="Nome della carta da rimuovere")
    async def banlist_rimuovi(
        self,
        interaction: discord.Interaction,
        carta: str,
    ):
        if not await self._check_tournament_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        session = get_session()
        if session is None:
            return await interaction.followup.send("Database non disponibile.", ephemeral=True)
        try:
            repo = BanlistRepository(session)
            ok = await repo.remove_card(carta)
            if ok:
                await self._log(
                    "INFO", "BANLIST_REMOVE", user=interaction.user,
                    info=f"Rimossa: {carta}"
                )
                await interaction.followup.send(
                    f"Carta **{carta}** rimossa dalla banlist.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Carta **{carta}** non trovata nella banlist.", ephemeral=True
                )
        finally:
            await session.close()


async def setup(bot):
    await bot.add_cog(TournamentSystemCog(bot))
