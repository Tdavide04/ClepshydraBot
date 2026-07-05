import discord
from datetime import datetime

from cogs.deck_validation.models import DeckValidationResult


def build_result_embed(
    result: DeckValidationResult,
    member: discord.Member
) -> discord.Embed:
    color = discord.Color.green() if result.is_valid else discord.Color.red()
    embed = discord.Embed(
        title=f"Artisan Deck Check: {member.display_name}",
        description="Mazzo valido per Artisan" if result.is_valid else "Mazzo NON valido per Artisan",
        color=color,
        timestamp=datetime.now()
    )

    if result.banned_cards:
        embed.add_field(
            name="Carte Bannate",
            value="\n".join(result.banned_cards[:10]),
            inline=False
        )

    if result.illegal_rarity_cards:
        embed.add_field(
            name="Non Artisan Legal",
            value="\n".join(result.illegal_rarity_cards[:10]),
            inline=False
        )

    if result.invalid_cards:
        embed.add_field(
            name="Carte non trovate",
            value="\n".join(result.invalid_cards[:10]),
            inline=False
        )

    resoconto = (
        f"**Carte totali:** {result.total_cards}\n"
        f"**Mainboard:** {result.main_count}/60\n"
        f"**Sideboard:** {result.side_count}/15"
    )
    if result.banned_cards:
        resoconto += f"\n**Bannate:** {len(result.banned_cards)}"
    if result.illegal_rarity_cards:
        resoconto += f"\n**Illegali:** {len(result.illegal_rarity_cards)}"

    embed.add_field(name="Resoconto", value=resoconto, inline=False)

    return embed
