import discord
from datetime import datetime
from cogs.presentation.models import PresentationData


def build_preview_embed(member: discord.Member, data: PresentationData) -> discord.Embed:
    embed = discord.Embed(
        title=f"Nuova Presentazione: {member.display_name}",
        description=f"**Account originale:** `{member.name}`",
        color=discord.Color.green(),
        timestamp=datetime.now()
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(
        name="Dati Personali",
        value=(
            f"**Nome:** {data.nome}\n"
            f"**Nick Arena:** {data.nickname_arena}\n"
            f"**Anno nascita:** {data.anno_nascita}\n"
            f"**Lavoro:** {data.professione}\n"
            f"**Provenienza:** {data.provenienza}"
        ),
        inline=False
    )

    embed.add_field(
        name="Inizio Magic",
        value=(
            f"**Cartaceo:** {data.anno_cartaceo}\n"
            f"**Arena:** {data.anno_arena}"
        ),
        inline=False
    )

    embed.add_field(
        name="Preferenze",
        value=(
            f"**Formati:** {data.formati_preferiti_raw}\n"
            f"**Colori:** {data.colori_raw}\n"
            f"**Gilde:** {data.gilde_raw}"
        ),
        inline=False
    )

    if data.risultati:
        embed.add_field(
            name="Risultati",
            value=data.risultati,
            inline=False
        )

    if data.passioni:
        embed.add_field(
            name="Altre Passioni",
            value=data.passioni,
            inline=False
        )

    return embed


def build_published_embed(member: discord.Member, data: PresentationData) -> discord.Embed:
    return build_preview_embed(member, data)


def build_message_content(data: PresentationData) -> str:
    """Build the message content for the presentation channel - mimics V1 style."""
    lines = [
        f"**Nome:** {data.nome}",
        f"**Nickname Arena:** {data.nickname_arena}",
        f"**Anno di nascita:** {data.anno_nascita}",
        f"**Professione:** {data.professione}",
        f"**Provenienza:** {data.provenienza}",
        "",
        f"**Inizio Magic:**",
        f"- Cartaceo: {data.anno_cartaceo}",
        f"- Arena: {data.anno_arena}",
        "",
        f"**Preferenze:**",
        f"- Formati: {data.formati_preferiti_raw}",
        f"- Colori: {data.colori_raw}",
        f"- Gilde: {data.gilde_raw}",
    ]

    if data.risultati:
        lines.extend(["", f"**Risultati:** {data.risultati}"])

    if data.passioni:
        lines.extend(["", f"**Altre passioni:** {data.passioni}"])

    return "\n".join(lines)