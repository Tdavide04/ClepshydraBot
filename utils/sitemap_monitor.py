"""
sitemap_monitor.py

Logica condivisa dai monitor che seguono pagine Wizards via il sitemap XML
standard di magic.wizards.com (utils/arena_event_schedule.py e
utils/ban_announcement.py): entrambi scaricano quotidianamente lo stesso
sitemap.xml, scelgono la pagina di interesse piu' recente per `lastmod`
(Wizards non rimuove mai le pagine passate dal sitemap, quindi ne convivono
sempre diverse) e tengono lo stato "ultima pagina vista" su un JSON locale
con scrittura atomica. Estratto qui dopo che il secondo monitor
(ban_announcement.py) ha duplicato byte-per-byte questa parte dal primo -
il filtro delle URL di interesse e il parsing del contenuto della pagina
restano invece in ciascun modulo, e' l'unica parte davvero diversa tra i due
(pattern di URL, e struttura HTML, differenti).
"""

import json
import os

import aiohttp

SITEMAP_URL = "https://magic.wizards.com/en/sitemap.xml"

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Entrambi i monitor controllano il sitemap ogni 24h: e' una GET economica
# su un file statico, mentre il contenuto reale che interessa (una nuova
# pagina Event Schedule o un nuovo Banned and Restricted Announcement)
# cambia molto piu' di rado - girare spesso costa pochissimo e riduce la
# latenza con cui la community viene informata.
_CHECK_INTERVAL_SECONDS = 24 * 60 * 60


def load_json_state(path: str, default: dict) -> dict:
    """Carica un dict JSON da disco, o una copia di `default` se il file
    non esiste ancora (primo avvio su una macchina nuova)."""

    if not os.path.exists(path):
        return dict(default)

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_state(path: str, data: dict) -> None:
    """Scrittura atomica (file `.tmp` + `os.replace`): un crash a meta'
    salvataggio lascia lo stato precedente intatto invece di un JSON
    corrotto/troncato."""

    os.makedirs(os.path.dirname(path), exist_ok=True)

    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp_path, path)


def pick_latest_by_lastmod(entries: dict[str, str]) -> tuple[str, str] | None:
    """Tra le pagine trovate sul sitemap, individua quella con il `lastmod`
    piu' recente. I lastmod sono timestamp ISO-8601 a larghezza fissa (es.
    '2026-09-02T16:05:08.364Z'), quindi il confronto lessicografico tra
    stringhe coincide con l'ordine cronologico, senza dover fare parsing di
    date."""

    if not entries:
        return None

    return max(entries.items(), key=lambda item: item[1])


async def fetch_sitemap_xml(session: aiohttp.ClientSession) -> str | None:
    """Scarica il body XML di sitemap.xml, o None se la richiesta fallisce -
    il chiamante decide come trattare l'assenza (i due monitor la trattano
    come 'nessuna pagina trovata', non come errore fatale)."""

    async with session.get(SITEMAP_URL) as response:
        if response.status != 200:
            print(f"[SITEMAP FAIL] {SITEMAP_URL} -> {response.status}")
            return None
        return await response.text()


async def fetch_page_html(session: aiohttp.ClientSession, url: str, log_prefix: str) -> str | None:
    """GET generica di una singola pagina. `log_prefix` distingue in
    console quale monitor ha generato l'eventuale fallimento (es.
    'EVENT SCHEDULE', 'BAN ANNOUNCEMENT')."""

    async with session.get(url) as response:
        if response.status != 200:
            print(f"[{log_prefix} FETCH FAIL] {url} -> {response.status}")
            return None
        return await response.text()
