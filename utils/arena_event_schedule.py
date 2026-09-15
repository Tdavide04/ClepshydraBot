"""
arena_event_schedule.py

Rileva la pubblicazione o l'aggiornamento delle pagine "[Set] MTG Arena Event
Schedule" di Wizards (una per espansione, non settimanali come i post
"MTG Arena Announcements") e ne estrae la sezione "Full Event Calendar",
per notificare la community senza dover controllare manualmente il sito.

Approccio:
- magic.wizards.com/en/sitemap.xml e' un sitemap XML standard con <lastmod>
  per ogni pagina del sito. Filtrando le URL "*-event-schedule" sotto
  /en/news/mtg-arena/ si ottiene l'elenco delle pagine schedule esistenti
  senza dover indovinare in anticipo il nome del prossimo set.
- Queste pagine vengono aggiornate IN PLACE da Wizards durante il ciclo di
  vita del set (es. per aggiungere le settimane successive di rotazione
  Quick Draft), non solo pubblicate una volta: per questo si confronta il
  lastmod, non solo la presenza dell'URL.
- Wizards NON rimuove dal sitemap le pagine dei set passati: a un dato
  momento il sitemap ne contiene sempre diverse (una per ogni set recente).
  Interessa solo quella del set ATTUALMENTE attivo, non l'intero storico -
  per questo si guarda solo la pagina con il lastmod piu' recente, non tutte
  quelle trovate. Senza questo filtro, la prima esecuzione su una macchina
  nuova (stato vuoto) segnalerebbe come "nuove" anche pagine di set gia'
  conclusi da mesi, producendo un flood di notifiche per eventi non piu'
  rilevanti.
- Il check del sitemap e' economico (una GET su un file statico) e viene
  fatto quotidianamente; il fetch+parsing della singola pagina (piu'
  costoso e fragile, essendo HTML non un formato dati) scatta solo per le
  URL il cui lastmod risulta nuovo o cambiato rispetto allo stato salvato.
- La sezione "Full Event Calendar" di queste pagine e' HTML realmente
  strutturato (non prosa libera come i post Announcements settimanali):
  blocchi <h2>/<h3>/<h4>Categoria</h2> seguiti da <ul><li>intervallo di
  date: descrizione</li></ul>. Se questa struttura non viene trovata (drift
  del sito), la pagina viene segnalata come non interpretabile invece di
  pubblicare un riassunto incompleto o sbagliato.
"""

import asyncio
import calendar
import json
import os
import re
import html as html_module
import xml.etree.ElementTree as ET
from datetime import date

import aiohttp
import discord

STATE_PATH = "data/arena_event_schedule_state.json"

SITEMAP_URL = "https://magic.wizards.com/en/sitemap.xml"

# Sotto-percorso su cui vivono sia i post settimanali "announcements-*" sia
# le pagine dedicate "*-event-schedule" che questo modulo osserva.
_NEWS_URL_PREFIX = "https://magic.wizards.com/en/news/mtg-arena/"

_EVENT_SCHEDULE_URL_RE = re.compile(
    re.escape(_NEWS_URL_PREFIX) + r"[a-z0-9-]+-event-schedule$"
)

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Il sitemap e la pagina cambiano raramente (nuovo set ogni 6-9 settimane, con
# eventuali aggiornamenti in-place a meta' ciclo), ma il check e' una singola
# GET economica su un file statico: girare spesso costa pochissimo e riduce
# la latenza con cui la community viene informata, a differenza del parsing
# della singola pagina (piu' fragile) che scatta solo sui cambiamenti reali.
_CHECK_INTERVAL_SECONDS = 24 * 60 * 60

_HEADING_LIST_RE = re.compile(
    r"<h[234]>\s*([^<]+?)\s*</h[234]>\s*<ul>(.*?)</ul>",
    re.DOTALL,
)
_LI_RE = re.compile(r"<li>(.*?)</li>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_CALENDAR_HEADING_RE = re.compile(r"<h[234]>\s*Full Event Calendar\s*</h[234]>")
_ARTICLE_END_RE = re.compile(r"</article>")

# Ogni voce della "Full Event Calendar" ha il formato osservato dal vivo
# "Mese Giorno[-Mese] Giorno: Nome evento" (es. "August 11-September 29: ...",
# "August 11-19: ..."), senza anno esplicito - il mese di fine e' opzionale
# quando il range resta nello stesso mese. Il trattino puo' essere un en dash
# "-" (quello effettivamente usato dal sito) o un normale "-".
_ENTRY_DATE_RE = re.compile(
    r"^(?P<m1>[A-Za-z]+)\s+(?P<d1>\d{1,2})\s*[–-]\s*"
    r"(?:(?P<m2>[A-Za-z]+)\s+)?(?P<d2>\d{1,2})\s*:\s*(?P<name>.+)$"
)

_MONTH_NUMBERS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

MONTHS_IT = {
    1: "Gennaio", 2: "Febbraio", 3: "Marzo", 4: "Aprile",
    5: "Maggio", 6: "Giugno", 7: "Luglio", 8: "Agosto",
    9: "Settembre", 10: "Ottobre", 11: "Novembre", 12: "Dicembre",
}

_state_cache: dict | None = None


# ==========================================
# LOAD / SAVE STATO
# ==========================================

def _load_state() -> dict:
    global _state_cache

    if _state_cache is not None:
        return _state_cache

    if not os.path.exists(STATE_PATH):
        _state_cache = {"latest_url": None, "latest_lastmod": None}
        return _state_cache

    with open(STATE_PATH, "r", encoding="utf-8") as f:
        _state_cache = json.load(f)

    return _state_cache


def _save_state(data: dict) -> None:
    global _state_cache

    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)

    tmp_path = STATE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp_path, STATE_PATH)

    _state_cache = data


def invalidate_state_cache() -> None:
    global _state_cache
    _state_cache = None


# ==========================================
# SITEMAP
# ==========================================

def _parse_sitemap_xml(body: str) -> dict[str, str]:
    """Estrae {url: lastmod} per le sole pagine '*-event-schedule' sotto
    /en/news/mtg-arena/. Separata dal fetch HTTP per essere testabile senza
    mockare aiohttp."""

    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        print(f"[SITEMAP PARSE ERROR] {e}")
        return {}

    found: dict[str, str] = {}
    for url_el in root.findall("sm:url", _SITEMAP_NS):
        loc_el = url_el.find("sm:loc", _SITEMAP_NS)
        lastmod_el = url_el.find("sm:lastmod", _SITEMAP_NS)

        if loc_el is None or loc_el.text is None:
            continue

        loc = loc_el.text.strip()
        if not _EVENT_SCHEDULE_URL_RE.match(loc):
            continue

        found[loc] = lastmod_el.text.strip() if lastmod_el is not None and lastmod_el.text else ""

    return found


async def _fetch_sitemap_event_schedule_urls(
    session: aiohttp.ClientSession,
) -> dict[str, str]:
    """Scarica il sitemap e restituisce {url: lastmod} per le sole pagine
    '*-event-schedule' sotto /en/news/mtg-arena/."""

    async with session.get(SITEMAP_URL) as response:
        if response.status != 200:
            print(f"[SITEMAP FAIL] {SITEMAP_URL} -> {response.status}")
            return {}
        body = await response.text()

    return _parse_sitemap_xml(body)


# ==========================================
# PARSING PAGINA "FULL EVENT CALENDAR"
# ==========================================

def _strip_tags(text: str) -> str:
    return html_module.unescape(_TAG_RE.sub("", text)).strip()


def parse_full_event_calendar(page_html: str) -> dict[str, list[str]] | None:
    """Estrae {categoria: [voci]} dalla sezione 'Full Event Calendar' di una
    pagina Event Schedule. Restituisce None se la sezione non viene trovata
    (drift strutturale del sito) - il chiamante deve trattarlo come
    'non interpretabile', non come 'nessun evento'."""

    calendar_match = _CALENDAR_HEADING_RE.search(page_html)
    if not calendar_match:
        return None

    section = page_html[calendar_match.end():]
    end_match = _ARTICLE_END_RE.search(section)
    if end_match:
        section = section[:end_match.start()]

    categories: dict[str, list[str]] = {}
    for heading, list_block in _HEADING_LIST_RE.findall(section):
        category = _strip_tags(heading)
        entries = [_strip_tags(li) for li in _LI_RE.findall(list_block)]
        entries = [e for e in entries if e]
        if category and entries:
            categories[category] = entries

    return categories or None


# ==========================================
# PARSING DATE VOCE + RAGGRUPPAMENTO PER MESE
# ==========================================

def parse_event_entry(text: str) -> dict | None:
    """Estrae mese/giorno di inizio e fine da una voce testuale della
    'Full Event Calendar' (es. 'August 11-September 29: Nome evento' o
    'August 11-19: Nome evento'). Restituisce None se il testo non segue il
    formato atteso - il chiamante deve escludere la voce dal calendario a
    immagine invece di inventare una data, ma puo' comunque mostrarla intatta
    negli embed testuali (che non dipendono da questo parsing)."""

    match = _ENTRY_DATE_RE.match(text.strip())
    if not match:
        return None

    m1 = _MONTH_NUMBERS.get(match.group("m1").lower())
    m2_raw = match.group("m2")
    m2 = _MONTH_NUMBERS.get(m2_raw.lower()) if m2_raw else m1

    if m1 is None or m2 is None:
        return None

    try:
        d1 = int(match.group("d1"))
        d2 = int(match.group("d2"))
    except ValueError:
        return None

    return {
        "start_month": m1,
        "start_day": d1,
        "end_month": m2,
        "end_day": d2,
        "name": match.group("name").strip(),
    }


def _infer_start_year(start_month: int, reference: date) -> int:
    """Assume l'anno corrente al momento del check; se il mese di inizio
    risulta molto "indietro" rispetto al mese corrente (es. Gennaio quando il
    check avviene a Dicembre), lo si considera dell'anno prossimo invece che
    di uno gia' passato - copre il turno di anno per un range pubblicato a
    fine anno. La soglia (6 mesi) evita falsi positivi sulle voci "Flashback"
    che si riferiscono correttamente a un mese recente dello stesso anno."""

    diff = start_month - reference.month
    if diff <= -6:
        return reference.year + 1
    return reference.year


def build_month_calendar(
    categories: dict[str, list[str]],
    reference_date: date | None = None,
) -> dict[tuple[int, int], dict[str, list[tuple[int, int, str]]]]:
    """Trasforma {categoria: [voci testuali]} in
    {(anno, mese): {categoria: [(giorno_inizio, giorno_fine, nome), ...]}},
    spezzando ogni range che attraversa piu' mesi in un segmento per mese
    toccato (i giorni vengono ritagliati ai limiti del mese). Voci non
    parsabili (formato data imprevisto) vengono escluse silenziosamente -
    restano visibili solo negli embed testuali, che non passano da qui."""

    if reference_date is None:
        reference_date = date.today()

    result: dict[tuple[int, int], dict[str, list[tuple[int, int, str]]]] = {}

    for category, entries in categories.items():
        for entry_text in entries:
            parsed = parse_event_entry(entry_text)
            if parsed is None:
                continue

            start_year = _infer_start_year(parsed["start_month"], reference_date)
            end_year = start_year
            if parsed["end_month"] < parsed["start_month"]:
                end_year = start_year + 1

            cur_year, cur_month = start_year, parsed["start_month"]
            while (cur_year, cur_month) <= (end_year, parsed["end_month"]):
                if (cur_year, cur_month) == (start_year, parsed["start_month"]):
                    seg_start = parsed["start_day"]
                else:
                    seg_start = 1

                if (cur_year, cur_month) == (end_year, parsed["end_month"]):
                    seg_end = parsed["end_day"]
                else:
                    seg_end = calendar.monthrange(cur_year, cur_month)[1]

                month_key = (cur_year, cur_month)
                result.setdefault(month_key, {}).setdefault(category, []).append(
                    (seg_start, seg_end, parsed["name"])
                )

                if cur_month == 12:
                    cur_year, cur_month = cur_year + 1, 1
                else:
                    cur_month += 1

    return result


def _pick_latest(entries: dict[str, str]) -> tuple[str, str] | None:
    """Tra le pagine Event Schedule trovate sul sitemap, individua quella con
    il lastmod piu' recente - in pratica il set attualmente attivo. I lastmod
    sono timestamp ISO-8601 a larghezza fissa (es. '2026-09-02T16:05:08.364Z'),
    quindi il confronto lessicografico tra stringhe coincide con l'ordine
    cronologico, senza dover fare parsing di date."""

    if not entries:
        return None

    return max(entries.items(), key=lambda item: item[1])


async def _fetch_page_html(session: aiohttp.ClientSession, url: str) -> str | None:
    async with session.get(url) as response:
        if response.status != 200:
            print(f"[EVENT SCHEDULE FETCH FAIL] {url} -> {response.status}")
            return None
        return await response.text()


# ==========================================
# CHECK (API pubblica)
# ==========================================

async def check_event_schedule_updates(force: bool = False) -> list[dict]:
    """Individua la pagina Event Schedule PIU' RECENTE (per lastmod) sul
    sitemap e, se e' nuova o cambiata rispetto all'ultima nota (o comunque,
    se force=True), la scarica e prova a interpretare la sezione
    'Full Event Calendar'. Le pagine di set passati ancora presenti sul
    sitemap vengono ignorate (vedi _pick_latest).

    Ritorna una lista con zero o un elemento {url, lastmod, categories}
    (categories None se il parsing e' fallito - il chiamante deve segnalarlo
    come tale, non ignorarlo silenziosamente) - la forma a lista resta per
    compatibilita' con i chiamanti che iterano sul risultato. Aggiorna e
    salva lo stato solo se la pagina e' stata effettivamente processata in
    questa chiamata.
    """

    headers = {"User-Agent": "ClepshydraBot/1.0 (Discord Tournament Bot)"}
    timeout = aiohttp.ClientTimeout(total=60)

    state = _load_state()

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        current = await _fetch_sitemap_event_schedule_urls(session)

        latest = _pick_latest(current)
        if latest is None:
            print("[EVENT SCHEDULE] nessuna pagina Event Schedule trovata sul sitemap")
            return []

        url, lastmod = latest

        already_seen = (
            state.get("latest_url") == url
            and state.get("latest_lastmod") == lastmod
        )
        if already_seen and not force:
            print(f"[EVENT SCHEDULE] nessun cambiamento (piu' recente: {url})")
            return []

        print(f"[EVENT SCHEDULE] pagina nuova/aggiornata: {url}")

        page_html = await _fetch_page_html(session, url)

        if page_html is None:
            # Fetch fallito: non aggiorniamo lo stato, ci riproviamo al
            # prossimo giro invece di marcarla come vista.
            print(f"[EVENT SCHEDULE] fetch fallito per {url}, ritento al prossimo giro")
            return []

        categories = parse_full_event_calendar(page_html)

    _save_state({"latest_url": url, "latest_lastmod": lastmod})

    if categories is None:
        print(f"[EVENT SCHEDULE] {url}: sezione 'Full Event Calendar' non riconosciuta")
    else:
        print(f"[EVENT SCHEDULE] {url}: {len(categories)} categorie interpretate")

    return [{"url": url, "lastmod": lastmod, "categories": categories}]


async def periodic_event_schedule_check_loop(
    bot=None,
    interval_seconds: int = _CHECK_INTERVAL_SECONDS,
) -> None:
    """Task in background: controlla quotidianamente il sitemap e notifica su
    Discord ogni pagina Event Schedule nuova o aggiornata. Il primo giro
    parte subito all'avvio, come periodic_spg_refresh_loop."""

    while True:
        try:
            results = await check_event_schedule_updates()

            if results and bot is not None:
                logger = bot.get_cog("Logger")
                if logger:
                    for result in results:
                        await send_event_schedule_log(logger, result, user=None, forced=False)

        except Exception as e:
            print(f"[EVENT SCHEDULE AUTO-CHECK] errore: {e}")

        await asyncio.sleep(interval_seconds)


async def send_event_schedule_log(logger, result: dict, user, forced: bool) -> None:
    """Posta su Discord (via Logger cog) l'esito del controllo di una singola
    pagina Event Schedule. Esposta come funzione pubblica perche' usata sia
    dal loop automatico sia dal comando admin manuale (stesso formato di
    log per entrambi i percorsi).

    Genera e allega un'immagine calendario per mese (EventCalendarImageGenerator)
    invece di descrivere gli eventi a parole in campi embed - sostituisce il
    design precedente (un campo per categoria, diviso in piu' messaggi),
    poco leggibile con le 13-15 categorie reali. Import di
    EventCalendarImageGenerator locale alla funzione (non in cima al modulo)
    per evitare un import circolare: quel modulo importa MONTHS_IT da qui."""

    url = result["url"]
    categories = result["categories"]
    prefix = "Controllo manuale forzato" if forced else "Controllo automatico"

    if categories is None:
        await logger.send_log(
            level="WARN",
            event="ARENA_EVENT_SCHEDULE_UNPARSEABLE",
            user=user,
            info=(
                f"{prefix}: trovato aggiornamento su {url} ma la sezione "
                f"'Full Event Calendar' non e' stata riconosciuta (possibile "
                f"cambio di struttura del sito). Controllo manuale consigliato."
            ),
        )
        return

    month_calendar = build_month_calendar(categories)

    if not month_calendar:
        await logger.send_log(
            level="WARN",
            event="ARENA_EVENT_SCHEDULE_NO_DATES",
            user=user,
            info=(
                f"{prefix}: {url} interpretata ma nessuna voce aveva un "
                f"formato data riconoscibile - calendario non generato, "
                f"controllo manuale consigliato."
            ),
        )
        return

    from utils.event_calendar_image_generator import EventCalendarImageGenerator

    files = [
        discord.File(
            EventCalendarImageGenerator.create_month_calendar(year, month, category_entries),
            filename=f"calendario_{year}_{month:02d}.png",
        )
        for (year, month), category_entries in sorted(month_calendar.items())
    ]

    await logger.send_log(
        level="INFO",
        event="ARENA_EVENT_SCHEDULE_UPDATED",
        user=user,
        info=f"{prefix}: {url}",
        files=files,
    )
