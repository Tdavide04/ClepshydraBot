import discord

from utils.tournament_logic import (
    omw_bar,
    rank_label,
    split_into_columns,
    split_field_value,
)

EMBED_COLOR_STANDINGS = 0xC9A227
EMBED_COLOR_PAIRINGS = 0x1D9E75
EMBED_COLOR_START = 0x5865F2
EMBED_COLOR_TOP8 = 0xE24B4A


def build_standings_embed(
    tournament_name: str,
    tournament_id: int,
    round_number: int,
    entries: list,
    player_count: int,
) -> discord.Embed:
    if round_number == 0:
        title = f"\U0001F3C6 Classifica \u2014 {tournament_name}"
        description = f"Iscrizioni aperte \u00B7 {player_count} giocatori"
    else:
        title = f"\u26A1 Classifica \u2014 {tournament_name}"
        description = f"Dopo il Round {round_number}"

    embed = discord.Embed(
        title=title,
        description=description,
        color=EMBED_COLOR_STANDINGS,
    )

    lines = []
    for entry in entries:
        pct = entry.opponent_win_percent * 100
        bar = omw_bar(pct)
        gw_pct = entry.game_win_percent * 100 if entry.game_win_percent else 0.0
        deck = entry.deck_name if entry.deck_name else "\u2014"
        lines.append(
            f"{rank_label(entry.rank)} **{entry.player_name}** \u2014 {deck}\n"
            f"\u2523 {entry.points:.0f} pt  \u2022  {entry.wins}W/{entry.losses}L/{entry.draws}T\n"
            f"\u2523 GW: {gw_pct:.1f}%\n"
            f"\u2517 OMW: {bar}"
        )

    if not lines:
        lines.append("Nessun dato disponibile.")

    if len(lines) <= 2:
        embed.add_field(
            name="Classifica",
            value="\n\n".join(lines),
            inline=False,
        )
    else:
        left, right = split_into_columns(lines)
        mid = len(left)
        total = len(left) + len(right)

        left_chunks = split_field_value(left)
        right_chunks = split_field_value(right)

        for i, chunk in enumerate(left_chunks):
            suffix = " (cont.)" if i > 0 else ""
            embed.add_field(
                name=f"Posizioni 1\u2013{mid}{suffix}",
                value=chunk,
                inline=True,
            )

        for i, chunk in enumerate(right_chunks):
            suffix = " (cont.)" if i > 0 else ""
            embed.add_field(
                name=f"Posizioni {mid + 1}\u2013{total}{suffix}",
                value=chunk,
                inline=True,
            )

    embed.set_footer(text=f"\U0001FAAA Torneo ID: {tournament_id}")
    return embed


def build_pairings_embed(
    tournament_name: str,
    tournament_id: int,
    round_number: int,
    pairings: list[dict],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"\U0001F3AF Round {round_number} \u2014 Accoppiamenti",
        color=EMBED_COLOR_PAIRINGS,
    )

    lines = []
    for p in pairings:
        table = p["table"]
        p1 = p["player1"]
        p1_deck = p.get("player1_deck")
        if p1_deck:
            p1 = f"{p['player1']} ({p1_deck})"
        if p["player2"] is None:
            lines.append(f"Tavolo {table}  {p1} \u2014 BYE \U0001F50A")
        else:
            p2 = p["player2"]
            p2_deck = p.get("player2_deck")
            if p2_deck:
                p2 = f"{p['player2']} ({p2_deck})"
            lines.append(f"Tavolo {table}  {p1} vs {p2}")

    if not lines:
        lines.append("Nessun accoppiamento.")

    embed.add_field(
        name="Accoppiamenti",
        value="\n".join(lines),
        inline=False,
    )

    embed.set_footer(text=f"\U0001FAAA Torneo ID: {tournament_id}")
    return embed


def build_start_embed(
    tournament_name: str,
    tournament_id: int,
    players: list[tuple[str, str]],
    round_count: int,
) -> discord.Embed:
    embed = discord.Embed(
        title="\U0001F680 Torneo Iniziato!",
        description=f"**{tournament_name}** \u2014 {len(players)} giocatori",
        color=EMBED_COLOR_START,
    )

    lines = []
    for i, (name, deck) in enumerate(players, 1):
        deck_str = deck if deck else "\u2014"
        lines.append(f"{i}. **{name}**\n   {deck_str}")

    if len(players) > 12:
        left, right = split_into_columns(lines)
        mid = len(left)
        total = len(left) + len(right)

        left_chunks = split_field_value(left)
        right_chunks = split_field_value(right)

        for i, chunk in enumerate(left_chunks):
            suffix = " (cont.)" if i > 0 else ""
            embed.add_field(
                name=f"Partecipanti (1\u2013{mid}){suffix}",
                value=chunk,
                inline=True,
            )

        for i, chunk in enumerate(right_chunks):
            suffix = " (cont.)" if i > 0 else ""
            embed.add_field(
                name=f"Partecipanti ({mid + 1}\u2013{total}){suffix}",
                value=chunk,
                inline=True,
            )
    else:
        chunks = split_field_value(lines)
        for i, chunk in enumerate(chunks):
            suffix = f" (parte {i + 1})" if len(chunks) > 1 else ""
            embed.add_field(
                name=f"Partecipanti{suffix}",
                value=chunk,
                inline=False,
            )

    embed.set_footer(text=f"\U0001FAAA Torneo ID: {tournament_id}")
    return embed


def build_top8_embed(
    tournament_name: str,
    tournament_id: int,
    bracket: dict,
) -> discord.Embed:
    embed = discord.Embed(
        title="\U0001F396\uFE0F Top 8 \u2014 Eliminazione Diretta",
        color=EMBED_COLOR_TOP8,
    )

    qf_lines = []
    for qf in bracket.get("quarterfinals", []):
        qf_lines.append(
            f"QF{qf['number']}  {qf['player1']} vs {qf['player2']}"
        )
    if qf_lines:
        embed.add_field(
            name="Quarti di Finale",
            value="\n".join(qf_lines),
            inline=True,
        )

    sf_lines = []
    for sf in bracket.get("semifinals", []):
        sf_lines.append(
            f"SF{sf['number']}  {sf['player1']} vs {sf['player2']}"
        )
    if sf_lines:
        embed.add_field(
            name="Semifinali",
            value="\n".join(sf_lines),
            inline=True,
        )

    final = bracket.get("final")
    if final:
        embed.add_field(
            name="Finale",
            value=f"\U0001F3C6  {final['player1']} vs {final['player2']}",
            inline=True,
        )

    champion = bracket.get("champion")
    if champion:
        embed.add_field(
            name="Campione",
            value=f"\U0001F451 **{champion['name']}**\n   {champion.get('deck', '\u2014')}",
            inline=True,
        )

    embed.set_footer(text=f"\U0001FAAA Torneo ID: {tournament_id}")
    return embed
