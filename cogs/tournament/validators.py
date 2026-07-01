import os
import re

from cogs.tournament.models import DeckEntry


BANLIST_PATH = "cards.txt"


def load_banlist(path: str = BANLIST_PATH) -> set[str]:
    banned: set[str] = set()
    if not os.path.exists(path):
        return banned
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if not name:
                continue
            banned.add(name.lower())
            if " // " in name:
                banned.add(name.split(" // ")[0].strip().lower())
    return banned


def parse_decklist(raw: str) -> tuple[list[DeckEntry], int, str]:
    pattern = r"^(\d+)\s+(.+)"
    entries: list[DeckEntry] = []
    totale = 0
    in_side = False
    deck_name = "ARTISAN DECK"

    lines = raw.strip().split("\n")
    i = 0

    if lines and lines[0].strip().lower() == "about":
        i += 1
        if i < len(lines) and lines[i].strip():
            deck_name = lines[i].strip()
            i += 1

    for riga in lines[i:]:
        riga = riga.strip()
        if not riga or riga.lower() == "deck":
            continue
        if riga.lower() == "sideboard":
            in_side = True
            continue

        m = re.match(pattern, riga)
        if not m:
            continue

        qta = int(m.group(1))
        raw_nome = m.group(2).strip()
        raw_nome = re.sub(r"\s+\([A-Z0-9]+\)\s+\d+$", "", raw_nome).strip()
        nome = (
            raw_nome
            .replace("\u2019", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"')
        )

        if " // " in nome:
            nome = nome.split(" // ")[0].strip()

        entries.append(DeckEntry(quantity=qta, name=nome, is_sideboard=in_side))
        totale += qta

    return entries, totale, deck_name


def check_banlist(entries: list[DeckEntry], banlist: set[str]) -> list[str]:
    banned: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.name.lower() in banlist and entry.name not in seen:
            banned.append(entry.name)
            seen.add(entry.name)
    return banned


def validate_counts(main_count: int, side_count: int) -> list[str]:
    errors: list[str] = []
    if main_count < 60:
        errors.append(f"Mainboard {main_count}/60 (minimo 60)")
    if side_count > 15:
        errors.append(f"Sideboard {side_count}/15 (massimo 15)")
    return errors
