import discord
from discord.ext import commands
from datetime import datetime

from services.tournament_service import TournamentService
from utils.permissions import is_admin
from database.models import TournamentStatus, TournamentPlayer
from database import get_session
from cogs.tournament.service import ArtisanService
from cogs.tournament.validators import parse_decklist, validate_counts
from config.config import GUILD_ID


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
            title="\U0001f195 Nuovo Torneo",
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="Nome", value=f"**{tournament.name}**", inline=True)
        embed.add_field(name="ID", value=f"`{tournament.id}`", inline=True)
        embed.add_field(name="Formato", value=tournament.format, inline=True)
        if max_players:
            embed.add_field(name="Max Partecipanti", value=str(max_players), inline=True)
        embed.add_field(name="Stato", value="Iscrizioni aperte", inline=True)
        embed.set_footer(text=f"Creato da {interaction.user.display_name}")
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
        await interaction.response.defer(ephemeral=False)

        deck_name = self.titolo.value.strip() or "ARTISAN DECK"
        entries, total_cards, _ = parse_decklist(self.deck_list.value)

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


class TournamentSystemCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.service = TournamentService(bot)
        self.artisan_service = ArtisanService(bot)

    async def _log(self, level, event, user=None, info=None):
        logger = self.bot.get_cog("Logger")
        if logger:
            await logger.send_log(level=level, event=event, user=user, info=info)

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

    # ------------------------------------------------------------------
    # Comandi Admin
    # ------------------------------------------------------------------

    @discord.app_commands.command(
        name="crea_torneo",
        description="Crea un nuovo torneo"
    )
    @is_admin()
    async def crea_torneo(self, interaction: discord.Interaction):
        modal = CreaTorneoModal(self.service, self.bot)
        await interaction.response.send_modal(modal)

    @discord.app_commands.command(
        name="avvia_torneo",
        description="Avvia un torneo in attesa di iscrizioni"
    )
    @is_admin()
    @discord.app_commands.describe(
        torneo="ID o nome del torneo da avviare"
    )
    async def avvia_torneo(
        self,
        interaction: discord.Interaction,
        torneo: str,
    ):
        await interaction.response.defer(ephemeral=False)

        tournament = await self.service.find_tournament(torneo)
        if tournament is None:
            return await interaction.followup.send(
                f"Torneo `{torneo}` non trovato.", ephemeral=True
            )
        if tournament.status != TournamentStatus.REGISTRATION:
            return await interaction.followup.send(
                "Il torneo non \u00e8 in fase di iscrizioni.", ephemeral=True
            )

        msg = await self.service.start_tournament(tournament.id)

        if "non trovato" in msg or "non e attivo" in msg or "Servono almeno" in msg:
            return await interaction.followup.send(msg, ephemeral=True)

        embed = discord.Embed(
            title="\U0001f680 Torneo Iniziato!",
            description=msg,
            color=discord.Color.green(),
            timestamp=datetime.now(),
        )
        players = await self.service.get_registered_players(tournament.id)
        player_list = "\n".join(
            f"{i+1}. {self._player_display(p)}"
            for i, p in enumerate(players)
        )
        if player_list:
            embed.add_field(name="Partecipanti", value=player_list, inline=False)
        embed.set_footer(text=f"Torneo ID: {tournament.id}")
        await interaction.followup.send(embed=embed)

        await self._log(
            "INFO", "TOURNAMENT_STARTED", user=interaction.user,
            info=msg
        )

    @discord.app_commands.command(
        name="torneo_next_turn",
        description="Genera il prossimo turno del torneo attivo"
    )
    @is_admin()
    @discord.app_commands.describe(
        torneo="ID o nome del torneo"
    )
    async def torneo_next_turn(
        self,
        interaction: discord.Interaction,
        torneo: str,
    ):
        await interaction.response.defer(ephemeral=False)

        tournament = await self.service.find_tournament(torneo)
        if tournament is None:
            return await interaction.followup.send(
                f"Torneo `{torneo}` non trovato.", ephemeral=True
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

        await self._log(
            "INFO", "ROUND_GENERATED", user=interaction.user,
            info=f"Torneo **{tournament.name}** (ID: {tournament.id}) \u2014 Round {current_round}: {msg}"
        )

    # ------------------------------------------------------------------
    # Comandi Giocatori
    # ------------------------------------------------------------------

    @discord.app_commands.command(
        name="iscriviti",
        description="Iscriviti a un torneo"
    )
    @discord.app_commands.describe(
        torneo_id="ID del torneo a cui iscriversi"
    )
    async def iscriviti(
        self,
        interaction: discord.Interaction,
        torneo_id: int,
    ):
        tournament = await self.service.get_tournament(torneo_id)
        if tournament is None:
            return await interaction.response.send_message(
                "Torneo non trovato.", ephemeral=True
            )
        if tournament.status != TournamentStatus.REGISTRATION:
            return await interaction.response.send_message(
                "Il torneo non accetta iscrizioni.", ephemeral=True
            )

        already = await self.service.is_player_registered(
            torneo_id, interaction.user.id
        )
        if already:
            return await interaction.response.send_message(
                "Sei gi\u00e0 iscritto a questo torneo.", ephemeral=True
            )

        modal = IscrivitiModal(
            torneo_id, tournament.name, self.service, self.artisan_service, self.bot
        )
        await interaction.response.send_modal(modal)

    @discord.app_commands.command(
        name="left_torneo",
        description="Esci da un torneo prima che inizi"
    )
    @discord.app_commands.describe(
        torneo_id="ID del torneo da cui uscire"
    )
    async def left_torneo(
        self,
        interaction: discord.Interaction,
        torneo_id: int,
    ):
        await interaction.response.defer(ephemeral=False)

        tournament = await self.service.get_tournament(torneo_id)
        if tournament is None:
            return await interaction.followup.send(
                "Torneo non trovato.", ephemeral=True
            )
        if tournament.status != TournamentStatus.REGISTRATION:
            return await interaction.followup.send(
                "Non puoi uscire da un torneo gi\u00e0 iniziato o completato.", ephemeral=True
            )

        msg = await self.service.unregister_player(torneo_id, interaction.user.id)
        if "Non sei iscritto" in msg or "Torneo non trovato" in msg:
            return await interaction.followup.send(msg, ephemeral=True)

        embed = discord.Embed(
            title="\U0001f6aa Uscita dal torneo",
            description=f"{interaction.user.mention} \u00e8 uscito dal torneo **{tournament.name}**.",
            color=discord.Color.orange(),
            timestamp=datetime.now(),
        )
        embed.set_footer(text=f"Torneo ID: {torneo_id}")
        await interaction.followup.send(embed=embed)

    @discord.app_commands.command(
        name="risultato",
        description="Inserisci il risultato di una partita"
    )
    @discord.app_commands.describe(
        match_id="ID della partita",
        vincitore_id="ID del giocatore vincitore",
        risultato="win / loss / draw",
    )
    async def risultato(
        self,
        interaction: discord.Interaction,
        match_id: int,
        vincitore_id: int | None = None,
        risultato: str | None = None,
    ):
        await interaction.response.defer(ephemeral=False)
        msg = await self.service.submit_result(
            match_id, vincitore_id, risultato
        )

        embed = discord.Embed(
            title="\U0001f4dd Risultato Partita",
            description=msg,
            color=discord.Color.blue() if "Registrato" in msg else discord.Color.orange(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="Match ID", value=f"`{match_id}`", inline=True)
        if risultato:
            embed.add_field(name="Risultato", value=risultato.upper(), inline=True)
        embed.set_footer(text=f"Inserito da {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

        await self._log(
            "INFO" if "Registrato" in msg else "WARN",
            "MATCH_RESULT",
            user=interaction.user,
            info=f"Match {match_id}: {msg}"
        )

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
        await interaction.response.defer(ephemeral=False)

        if torneo_id is None:
            tournaments = await self.service.list_tournaments()
            active = [
                t for t in tournaments
                if t.status in (TournamentStatus.ACTIVE, TournamentStatus.COMPLETED)
            ]
            if not active:
                return await interaction.followup.send(
                    "Nessun torneo attivo o completato.", ephemeral=True
                )
            torneo_id = active[0].id

        result = await self.service.get_standings(torneo_id)
        if isinstance(result, str):
            return await interaction.followup.send(result, ephemeral=True)

        tournaments = await self.service.list_tournaments()
        tournament = next((t for t in tournaments if t.id == torneo_id), None)
        status_emoji = {
            TournamentStatus.REGISTRATION: "\U0001f4cb",
            TournamentStatus.ACTIVE: "\u26a1",
            TournamentStatus.COMPLETED: "\U0001f3c6",
        }
        emoji = status_emoji.get(tournament.status, "") if tournament else ""

        title = f"{emoji} Classifica: {tournament.name}" if tournament else "Classifica"

        embed = discord.Embed(
            title=title,
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )

        lines = []
        MEDALS = ["\U0001f947", "\U0001f948", "\U0001f949"]
        for entry in result[:20]:
            medal = MEDALS[entry.rank - 1] if 1 <= entry.rank <= 3 else f"`#{entry.rank:<2}`"
            deck_info = f" ({entry.deck_name})" if entry.deck_name else ""
            lines.append(
                f"{medal} **{entry.player_name}**{deck_info} \u2014 "
                f"{entry.points:.0f} pt "
                f"({entry.wins}W/{entry.losses}L/{entry.draws}T)"
            )

        if not lines:
            lines.append("Nessun dato disponibile.")

        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Torneo ID: {torneo_id}")
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
        await interaction.response.defer(ephemeral=False)

        if torneo_id is None:
            tournaments = await self.service.list_tournaments()
            active = [
                t for t in tournaments
                if t.status == TournamentStatus.ACTIVE
            ]
            if not active:
                return await interaction.followup.send(
                    "Nessun torneo attivo.", ephemeral=True
                )
            torneo_id = active[0].id

        current_round = await self.service.get_current_round(torneo_id)
        if current_round == 0:
            return await interaction.followup.send(
                "Il torneo non \u00e8 ancora iniziato.", ephemeral=True
            )

        matches = await self.service.get_matches(torneo_id)
        round_matches = [m for m in matches if m.round_number == current_round]

        tournaments = await self.service.list_tournaments()
        tournament = next((t for t in tournaments if t.id == torneo_id), None)
        title = (
            f"\U0001f3af Turno {current_round}: {tournament.name}"
            if tournament else f"\U0001f3af Turno {current_round}"
        )

        embed = discord.Embed(
            title=title,
            color=discord.Color.green(),
            timestamp=datetime.now(),
        )

        lines = []
        for m in round_matches:
            p1 = self._player_display(m.player1)
            table = f"`Tavolo {m.table_number:<2}`"
            if m.player2_id is not None and m.player2 is None:
                p2 = f"**Giocatore #{m.player2_id}**"
            elif m.player2 is not None:
                p2 = self._player_display(m.player2)
            else:
                p2 = None

            if p2 is not None:
                status = ""
                if m.result is not None:
                    status = " \u2705" if m.winner_id else " \U0001f91d"
                lines.append(f"{table} {p1} vs {p2}{status}")
            else:
                lines.append(f"{table} {p1} \u2014 **BYE** \U0001f50a")

        if not lines:
            lines.append("Nessun accoppiamento per questo turno.")

        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Torneo ID: {torneo_id} | Round {current_round}")
        await interaction.followup.send(embed=embed)

    @discord.app_commands.command(
        name="banlist",
        description="Visualizza le carte bannate"
    )
    async def banlist_lista(
        self,
        interaction: discord.Interaction,
    ):
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
