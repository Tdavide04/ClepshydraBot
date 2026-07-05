import discord
from cogs.presentation.models import PresentationData
from cogs.presentation.embeds import build_preview_embed
from cogs.presentation.modals import OptionalPresentationModal
from cogs.presentation.service import PresentationService


COLORI_OPTIONS = [
    discord.SelectOption(label="Bianco", value="bianco", emoji="⬜"),
    discord.SelectOption(label="Nero", value="nero", emoji="⬛"),
    discord.SelectOption(label="Rosso", value="rosso", emoji="🔴"),
    discord.SelectOption(label="Blu", value="blu", emoji="🔵"),
    discord.SelectOption(label="Verde", value="verde", emoji="🟢"),
    discord.SelectOption(label="Incolore", value="incolore", emoji="🩶"),
    discord.SelectOption(label="Tutti", value="tutti", emoji="🌈"),
    discord.SelectOption(label="N/A", value="n/a", emoji="❓"),
]

GILDE_OPTIONS = [
    discord.SelectOption(label="Azorius (WU)", value="azorius"),
    discord.SelectOption(label="Dimir (UB)", value="dimir"),
    discord.SelectOption(label="Izzet (UR)", value="izzet"),
    discord.SelectOption(label="Rakdos (BR)", value="rakdos"),
    discord.SelectOption(label="Golgari (BG)", value="golgari"),
    discord.SelectOption(label="Simic (UG)", value="simic"),
    discord.SelectOption(label="Boros (RW)", value="boros"),
    discord.SelectOption(label="Orzhov (WB)", value="orzhov"),
    discord.SelectOption(label="Selesnya (GW)", value="selesnya"),
    discord.SelectOption(label="Gruul (RG)", value="gruul"),
    discord.SelectOption(label="Esper", value="esper"),
    discord.SelectOption(label="Grixis", value="grixis"),
    discord.SelectOption(label="Bant", value="bant"),
    discord.SelectOption(label="Temur", value="temur"),
    discord.SelectOption(label="Jeskai", value="jeskai"),
    discord.SelectOption(label="Mardu", value="mardu"),
    discord.SelectOption(label="Abzan", value="abzan"),
    discord.SelectOption(label="Sultai", value="sultai"),
    discord.SelectOption(label="Jund", value="jund"),
    discord.SelectOption(label="Naya", value="naya"),
    discord.SelectOption(label="Tutte", value="tutte"),
    discord.SelectOption(label="N/A", value="n/a"),
]

FORMATI_CONSTRUCTED_OPTIONS = [
    discord.SelectOption(label="Standard", value="standard"),
    discord.SelectOption(label="Pioneer", value="pioneer"),
    discord.SelectOption(label="Modern", value="modern"),
    discord.SelectOption(label="Legacy", value="legacy"),
    discord.SelectOption(label="Vintage", value="vintage"),
    discord.SelectOption(label="Explorer", value="explorer"),
    discord.SelectOption(label="Historic", value="historic"),
    discord.SelectOption(label="Alchemy", value="alchemy"),
    discord.SelectOption(label="Timeless", value="timeless"),
    discord.SelectOption(label="Pauper", value="pauper"),
    discord.SelectOption(label="Penny", value="penny"),
    discord.SelectOption(label="Artisan", value="artisan"),
    discord.SelectOption(label="Nessuno", value="nessuno"),
]

FORMATI_LIMITED_OPTIONS = [
    discord.SelectOption(label="Draft", value="draft"),
    discord.SelectOption(label="Sealed", value="sealed"),
    discord.SelectOption(label="Limited", value="limited"),
    discord.SelectOption(label="Block / Blocco", value="block"),
    discord.SelectOption(label="Centurion", value="centurion"),
    discord.SelectOption(label="Commander", value="commander"),
    discord.SelectOption(label="Oathbreaker", value="oathbreaker"),
    discord.SelectOption(label="Brawl", value="brawl"),
    discord.SelectOption(label="Extended", value="extended"),
    discord.SelectOption(label="Two-Headed Giant", value="two-headed giant"),
    discord.SelectOption(label="Conspiracy", value="conspiracy"),
    discord.SelectOption(label="Planechase", value="planechase"),
    discord.SelectOption(label="Archenemy", value="archenemy"),
    discord.SelectOption(label="Momir", value="momir"),
    discord.SelectOption(label="Kitchen Table", value="kitchen table"),
    discord.SelectOption(label="Nessuno", value="nessuno"),
]


class ColoriSelect(discord.ui.Select):
    def __init__(self, data: PresentationData):
        default_values = data.colori if data.colori else []
        options = self._build_options(default_values)
        super().__init__(
            placeholder="Seleziona i colori preferiti",
            min_values=0,
            max_values=len(options),
            options=options,
            custom_id="colori_select"
        )
        self.data = data

    def _build_options(self, selected: list[str]) -> list[discord.SelectOption]:
        options = []
        for opt in COLORI_OPTIONS:
            opt_copy = discord.SelectOption(
                label=opt.label,
                value=opt.value,
                emoji=opt.emoji,
                default=opt.value in selected
            )
            options.append(opt_copy)
        return options

    async def callback(self, interaction: discord.Interaction):
        selected = self.values

        if "n/a" in selected and len(selected) > 1:
            selected = [v for v in selected if v != "n/a"]

        self.data.colori = selected
        await interaction.response.defer()


class GildeSelect(discord.ui.Select):
    def __init__(self, data: PresentationData):
        default_values = data.gilde if data.gilde else []
        options = self._build_options(default_values)
        super().__init__(
            placeholder="Seleziona le gilde preferite",
            min_values=0,
            max_values=len(options),
            options=options,
            custom_id="gilde_select"
        )
        self.data = data

    def _build_options(self, selected: list[str]) -> list[discord.SelectOption]:
        options = []
        for opt in GILDE_OPTIONS:
            opt_copy = discord.SelectOption(
                label=opt.label,
                value=opt.value,
                default=opt.value in selected
            )
            options.append(opt_copy)
        return options

    async def callback(self, interaction: discord.Interaction):
        selected = self.values

        if "n/a" in selected and len(selected) > 1:
            selected = [v for v in selected if v != "n/a"]
        if "tutte" in selected and len(selected) > 1:
            selected = ["tutte"]

        self.data.gilde = selected
        await interaction.response.defer()


class FormatiConstructedSelect(discord.ui.Select):
    def __init__(self, data: PresentationData):
        default_values = data.formati_construed if data.formati_construed else ["nessuno"]
        options = self._build_options(default_values)
        super().__init__(
            placeholder="Seleziona formati Constructed",
            min_values=0,
            max_values=len(options),
            options=options,
            custom_id="formati_construed_select"
        )
        self.data = data

    def _build_options(self, selected: list[str]) -> list[discord.SelectOption]:
        options = []
        for opt in FORMATI_CONSTRUCTED_OPTIONS:
            opt_copy = discord.SelectOption(
                label=opt.label,
                value=opt.value,
                default=opt.value in selected
            )
            options.append(opt_copy)
        return options

    async def callback(self, interaction: discord.Interaction):
        selected = self.values

        if "nessuno" in selected:
            if len(selected) > 1:
                selected = [v for v in selected if v != "nessuno"]
        elif not selected:
            selected = ["nessuno"]

        self.data.formati_construed = selected
        await interaction.response.defer()


class FormatiLimitedSelect(discord.ui.Select):
    def __init__(self, data: PresentationData):
        default_values = data.formati_limited if data.formati_limited else ["nessuno"]
        options = self._build_options(default_values)
        super().__init__(
            placeholder="Seleziona formati Limited & Special",
            min_values=0,
            max_values=len(options),
            options=options,
            custom_id="formati_limited_select"
        )
        self.data = data

    def _build_options(self, selected: list[str]) -> list[discord.SelectOption]:
        options = []
        for opt in FORMATI_LIMITED_OPTIONS:
            opt_copy = discord.SelectOption(
                label=opt.label,
                value=opt.value,
                default=opt.value in selected
            )
            options.append(opt_copy)
        return options

    async def callback(self, interaction: discord.Interaction):
        selected = self.values

        if "nessuno" in selected:
            if len(selected) > 1:
                selected = [v for v in selected if v != "nessuno"]
        elif not selected:
            selected = ["nessuno"]

        self.data.formati_limited = selected
        await interaction.response.defer()


class PreferencesView(discord.ui.View):
    def __init__(self, data: PresentationData = None, service=None):
        super().__init__(timeout=300)
        self.data = data
        self.service = service
        self.message = None
        self._member = None

        self.colori_select = ColoriSelect(self.data)
        self.gilde_select = GildeSelect(self.data)
        self.formati_construed_select = FormatiConstructedSelect(self.data)
        self.formati_limited_select = FormatiLimitedSelect(self.data)

        self.add_item(self.colori_select)
        self.add_item(self.gilde_select)
        self.add_item(self.formati_construed_select)
        self.add_item(self.formati_limited_select)

        continue_btn = discord.ui.Button(label="Continua", style=discord.ButtonStyle.primary, custom_id="prefs_continue")
        continue_btn.callback = self._on_continue
        self.add_item(continue_btn)

    async def _on_continue(self, interaction: discord.Interaction):
        async def after_optional_modal(interaction: discord.Interaction, data):
            member = interaction.user
            preview_embed = build_preview_embed(member, data)
            view = PreviewView(data, member)
            await interaction.followup.send(
                "Ecco l'anteprima della tua presentazione:",
                embed=preview_embed,
                view=view,
                ephemeral=True
            )

        modal = OptionalPresentationModal(self.data, on_complete=after_optional_modal)
        await interaction.response.send_modal(modal)


class PreviewView(discord.ui.View):
    def __init__(self, data: PresentationData, member=None):
        super().__init__(timeout=300)
        self.data = data
        self.member = member
        self.completed = False
        self.processing = False

        confirm_btn = discord.ui.Button(label="Conferma", style=discord.ButtonStyle.success, custom_id="preview_confirm", emoji="✅")
        confirm_btn.callback = self._on_confirm
        self.add_item(confirm_btn)

        cancel_btn = discord.ui.Button(label="Annulla", style=discord.ButtonStyle.danger, custom_id="preview_cancel", emoji="❌")
        cancel_btn.callback = self._on_cancel
        self.add_item(cancel_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.completed or self.processing:
            await interaction.response.send_message("Elaborazione in corso o gia completata.", ephemeral=True)
            return False
        return True

    async def _on_confirm(self, interaction: discord.Interaction):
        self.processing = True
        await interaction.response.defer(ephemeral=True)

        try:
            service = getattr(interaction.client, 'presentation_service', None) or PresentationService(interaction.client)
            await service.publish(interaction, self.data)
            self.completed = True
            await interaction.followup.send("✅ Benvenuto tra i Planeswalker!", ephemeral=True)
        except Exception as e:
            self.processing = False
            await interaction.followup.send(f"❌ Errore: {str(e)}", ephemeral=True)

    async def _on_cancel(self, interaction: discord.Interaction):
        await interaction.response.send_message("Presentazione annullata.", ephemeral=True)
        if self.message:
            await self.message.delete()