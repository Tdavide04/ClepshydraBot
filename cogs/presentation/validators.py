import re
from datetime import datetime
from typing import Tuple

VALIDI_colori = {
    "bianco", "nero", "rosso", "blu", "verde", "incolore",
    "white", "black", "red", "blue", "green", "colorless",
    "w", "b", "r", "u", "g", "5c",
    "tutti", "nessuno", "n/a"
}

VALIDI_gilde = {
    "azorius", "rakdos", "boros", "golgari",
    "orzhov", "selesnya", "gruul", "izzet",
    "dimir", "simic",
    "esper", "grixis", "bant", "temur",
    "jeskai", "mardu", "abzan", "sultai",
    "jund", "naya",
    "wu", "uw", "wb", "bw", "wr", "rw",
    "wg", "gw", "ub", "bu", "ur", "ru",
    "ug", "gu", "br", "rb", "bg", "gb",
    "rg", "gr",
    "nessuno", "n/a", "tutte"
}

VALIDI_formati_constructed = {
    "standard", "pioneer", "modern", "legacy", "vintage",
    "explorer", "historic", "alchemy", "timeless",
    "pauper", "penny", "artisan", "nessuno", "n/a"
}

VALIDI_formati_limited = {
    "draft", "sealed", "limited", "block", "blocco",
    "centurion", "commander", "oathbreaker", "brawl", "extended",
    "two-headed giant", "two headed giant", "conspiracy",
    "planechase", "archenemy", "momir", "kitchen table",
    "nessuno", "n/a"
}


def normalizza_colore(value: str) -> str:
    mapping = {
        "white": "Bianco", "w": "Bianco", "bianco": "Bianco",
        "black": "Nero", "b": "Nero", "nero": "Nero",
        "red": "Rosso", "r": "Rosso", "rosso": "Rosso",
        "blue": "Blu", "u": "Blu", "blu": "Blu",
        "green": "Verde", "g": "Verde", "verde": "Verde",
        "colorless": "Incolore", "incolore": "Incolore", "5c": "Incolore",
        "tutti": "Tutti", "nessuno": "Nessuno", "n/a": "N/A"
    }
    return mapping.get(value.lower().strip(), value)


def normalizza_gilda(value: str) -> str:
    mapping = {
        "wu": "Azorius", "uw": "Azorius", "azorius": "Azorius",
        "wr": "Boros", "rw": "Boros", "boros": "Boros",
        "wb": "Orzhov", "bw": "Orzhov", "orzhov": "Orzhov",
        "wg": "Selesnya", "gw": "Selesnya", "selesnya": "Selesnya",
        "ub": "Dimir", "bu": "Dimir", "dimir": "Dimir",
        "ur": "Izzet", "ru": "Izzet", "izzet": "Izzet",
        "br": "Rakdos", "rb": "Rakdos", "rakdos": "Rakdos",
        "bg": "Golgari", "gb": "Golgari", "golgari": "Golgari",
        "ug": "Simic", "gu": "Simic", "simic": "Simic",
        "gu": "Gruul", "rg": "Gruul", "gruul": "Gruul",
        "esper": "Esper", "grixis": "Grixis", "bant": "Bant", "temur": "Temur",
        "jeskai": "Jeskai", "mardu": "Mardu", "abzan": "Abzan", "sultai": "Sultai",
        "jund": "Jund", "naya": "Naya",
        "nessuno": "Nessuno", "n/a": "N/A", "tutte": "Tutte"
    }
    return mapping.get(value.lower().strip(), value.title())


def valida_anno_nascita(anno: str) -> bool:
    if not re.fullmatch(r"\d{4}", anno):
        return False
    anno_int = int(anno)
    anno_corrente = datetime.now().year
    eta = anno_corrente - anno_int
    return 1900 < anno_int < anno_corrente and eta >= 16


def valida_anno_cartaceo(anno: str) -> bool:
    if anno.lower() in ("mai", "n/a"):
        return True
    if not re.fullmatch(r"\d{4}", anno):
        return False
    anno_int = int(anno)
    return 1993 <= anno_int <= datetime.now().year


def valida_anno_arena(anno: str) -> bool:
    if anno.lower() in ("mai", "n/a"):
        return True
    if not re.fullmatch(r"\d{4}", anno):
        return False
    anno_int = int(anno)
    return 2017 <= anno_int <= datetime.now().year


def valida_colori(colori: list[str]) -> bool:
    if not colori:
        return True
    normalizzati = [normalizza_colore(c) for c in colori]
    # Confronta in minuscolo per matching case-insensitive
    return all(c.lower() in VALIDI_colori for c in normalizzati)


def valida_gilde(gilde: list[str]) -> bool:
    if not gilde:
        return True
    normalizzate = [normalizza_gilda(g) for g in gilde]
    # Confronta in minuscolo per matching case-insensitive
    return all(g.lower() in VALIDI_gilde for g in normalizzate)


def valida_formati(formati: list[str]) -> bool:
    if not formati:
        return True
    for f in formati:
        f_lower = f.lower().strip()
        if f_lower in ("nessuno", "n/a"):
            continue
        if f_lower not in VALIDI_formati_constructed and f_lower not in VALIDI_formati_limited:
            if "block" in f_lower or "blocco" in f_lower:
                continue
            return False
    return True


def valida_presentazione(data) -> tuple[list[str], list[str]]:
    errors = []

    if not valida_anno_nascita(data.anno_nascita):
        errors.append("Anno di nascita")

    if not valida_anno_cartaceo(data.anno_cartaceo):
        errors.append("Anno inizio Cartaceo")

    if not valida_anno_arena(data.anno_arena):
        errors.append("Anno inizio Arena")

    all_formati = list(data.formati_construed) + list(data.formati_limited)
    if not valida_formati(all_formati):
        errors.append("Formati preferiti")

    if not valida_colori(data.colori):
        errors.append("Colori preferiti")

    if not valida_gilde(data.gilde):
        errors.append("Gilde preferite")

    return [], errors