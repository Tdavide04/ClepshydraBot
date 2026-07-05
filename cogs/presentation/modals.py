from collections.abc import Callable
import discord
from cogs.presentation.models import (
    PresentationData,
    get_or_create_presentation_data,
)


class BasicPresentationModal(discord.ui.Modal, title="Presentazione Clepshydra"):
    def __init__(self, user_id: int, service=None, on_complete: Callable | None = None):
        super().__init__()
        self.user_id = user_id
        self.service = service
        self.presentation_data = None
        self.view = None
        self.on_complete = on_complete

        self.nome = discord.ui.TextInput(
            label="Nome",
            placeholder="Il tuo nome reale o quello che vuoi mostrare",
            min_length=2,
            max_length=100,
            required=True
        )
        self.nickname_arena = discord.ui.TextInput(
            label="Nickname Arena",
            placeholder="Il tuo nickname su Magic Arena",
            min_length=2,
            max_length=50,
            required=True
        )
        self.anno_nascita = discord.ui.TextInput(
            label="Anno di nascita",
            placeholder="Es. 1999",
            min_length=4,
            max_length=4,
            required=True
        )
        self.professione = discord.ui.TextInput(
            label="Professione",
            placeholder="Cosa fai nella vita?",
            min_length=2,
            max_length=100,
            required=True
        )
        self.provenienza = discord.ui.TextInput(
            label="Provenienza",
            placeholder="Citta o regione da cui scrivi",
            min_length=2,
            max_length=100,
            required=True
        )

        self.add_item(self.nome)
        self.add_item(self.nickname_arena)
        self.add_item(self.anno_nascita)
        self.add_item(self.professione)
        self.add_item(self.provenienza)

    async def on_submit(self, interaction: discord.Interaction):
        self.presentation_data = await get_or_create_presentation_data(self.user_id)
        self.presentation_data.nome = self.nome.value
        self.presentation_data.nickname_arena = self.nickname_arena.value
        self.presentation_data.anno_nascita = self.anno_nascita.value
        self.presentation_data.professione = self.professione.value
        self.presentation_data.provenienza = self.provenienza.value
        self.presentation_data.anno_cartaceo = ""
        self.presentation_data.anno_arena = ""

        await interaction.response.defer(ephemeral=True)

        if self.on_complete:
            await self.on_complete(interaction, self.presentation_data)


class OptionalPresentationModal(discord.ui.Modal, title="Dettagli Opzionali"):
    def __init__(self, presentation_data: PresentationData, on_complete: Callable | None = None):
        super().__init__()
        self.presentation_data = presentation_data
        self.view = None
        self.on_complete = on_complete

        self.anno_cartaceo = discord.ui.TextInput(
            label="Anno inizio Magic Cartaceo",
            placeholder="Es. 2018 o 'mai' / 'N/A'",
            min_length=2,
            max_length=4,
            required=True
        )
        self.anno_arena = discord.ui.TextInput(
            label="Anno inizio MTG Arena",
            placeholder="Es. 2020 o 'mai' / 'N/A'",
            min_length=2,
            max_length=4,
            required=True
        )
        self.risultati = discord.ui.TextInput(
            label="Risultati in Magic (opzionale)",
            placeholder="Eventuali risultati in tournament...",
            required=False,
            style=discord.TextStyle.paragraph
        )
        self.passioni = discord.ui.TextInput(
            label="Altre Passioni (opzionale)",
            placeholder="Altre passioni oltre Magic...",
            required=False,
            style=discord.TextStyle.paragraph
        )

        self.add_item(self.anno_cartaceo)
        self.add_item(self.anno_arena)
        self.add_item(self.risultati)
        self.add_item(self.passioni)

    async def on_submit(self, interaction: discord.Interaction):
        self.presentation_data.anno_cartaceo = self.anno_cartaceo.value
        self.presentation_data.anno_arena = self.anno_arena.value
        self.presentation_data.risultati = self.risultati.value
        self.presentation_data.passioni = self.passioni.value

        await interaction.response.defer(ephemeral=True)

        if self.on_complete:
            await self.on_complete(interaction, self.presentation_data)
