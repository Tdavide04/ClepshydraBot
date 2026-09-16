"""
ban_announcement.py

Rileva la pubblicazione di un nuovo "Banned and Restricted Announcement" di
Wizards (magic.wizards.com/en/news/announcements/banned-and-restricted-*),
pubblicato a cadenza fissa (circa ogni 6 settimane, sempre di lunedi') per
notificare la community - senza toccare la banlist Artisan del bot, che
resta un elenco curato a mano (vedi docs/banlist-system.md): nessuno dei
formati ufficiali Wizards elencati in questi annunci (Standard, Pioneer,
Modern, Legacy, Vintage, Pauper, Alchemy, Historic, Timeless, Brawl,
Competitive Brawl) e' l'Artisan homebrew di questa community, quindi non
esiste un modo corretto di applicare questi cambi al bot in automatico.

Approccio (stesso schema di arena_event_schedule.py):
- Il sitemap magic.wizards.com/en/sitemap.xml elenca anche questi annunci con
  <lastmod>. Come per le pagine Event Schedule, Wizards non rimuove gli
  annunci passati dal sitemap, quindi ne convivono sempre diversi - interessa
  solo quello con il lastmod piu' recente (_pick_latest), altrimenti il primo
  avvio su una macchina nuova segnalerebbe come "nuovo" tutto lo storico in
  una volta.
- Il check del sitemap gira quotidianamente (una GET economica su un file
  statico); il fetch+parsing della singola pagina (piu' fragile, HTML non
  dati strutturati) scatta solo se il lastmod dell'annuncio piu' recente e'
  cambiato rispetto allo stato salvato.
- A differenza dell'Event Schedule, qui non c'e' una sezione a elenco date
  ma prosa libera per formato. Osservato dal vivo pero' che ogni sezione ha
  un riepilogo affidabile e strutturato subito sotto l'heading del formato:
  <h2>Formato</h2> ... <p style="padding-left: 30px;">Carta X e' bannata.
  <br/>Carta Y e' sbannata.</p> (oppure letteralmente "No changes" quando
  nulla cambia in quel formato). E' solo questo riepilogo che viene estratto
  - il resto dell'articolo (analisi del metagame, decklist di esempio) non
  viene toccato: parsing troppo fragile per essere affidabile, e comunque
  fuori scopo per un bot che deve solo notificare, non riassumere l'articolo.
- Se non si trova nemmeno un heading di formato con il riepilogo atteso, la
  pagina viene segnalata come non interpretabile (drift del sito) invece di
  pubblicare un riassunto vuoto o sbagliato - stessa filosofia di
  parse_full_event_calendar() in arena_event_schedule.py.
"""

import asyncio
import html as html_module
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import aiohttp

from utils.arena_event_schedule import MONTHS_IT
from utils.sitemap_monitor import (
    _CHECK_INTERVAL_SECONDS,
    _SITEMAP_NS,
    fetch_page_html,
    fetch_sitemap_xml,
    load_json_state,
    pick_latest_by_lastmod,
    save_json_state,
)

STATE_PATH = "data/ban_announcement_state.json"

_ANNOUNCEMENTS_URL_PREFIX = "https://magic.wizards.com/en/news/announcements/banned-and-restricted-"

_BAN_ANNOUNCEMENT_URL_RE = re.compile(
    re.escape(_ANNOUNCEMENTS_URL_PREFIX) + r"[a-z0-9-]+$"
)

_H2_RE = re.compile(r"<h2[^>]*>\s*([^<]+?)\s*</h2>")

# Il riepilogo di ogni formato e' l'unico <p> con questo stile inline
# osservato sulle pagine reali - non un markup semantico dedicato, ma stabile
# su tutti gli annunci controllati (agosto/giugno/marzo 2026).
_SUMMARY_P_RE = re.compile(
    r'<p[^>]*style="[^"]*padding-left:\s*30px[^"]*"[^>]*>(.*?)</p>',
    re.DOTALL,
)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

_state_cache: dict | None = None


# ==========================================
# LOAD / SAVE STATO
# ==========================================

def _load_state() -> dict:
    global _state_cache

    if _state_cache is not None:
        return _state_cache

    _state_cache = load_json_state(STATE_PATH, {"latest_url": None, "latest_lastmod": None})
    return _state_cache


def _save_state(data: dict) -> None:
    global _state_cache

    save_json_state(STATE_PATH, data)
    _state_cache = data


def invalidate_state_cache() -> None:
    global _state_cache
    _state_cache = None


def get_latest_known_ban_announcement() -> dict:
    """Ritorna l'ultimo Banned and Restricted Announcement noto da stato
    salvato su disco - {"url": str | None, "lastmod": str | None} - senza
    alcuna richiesta di rete. Stesso ruolo di get_latest_known_event_schedule()
    in arena_event_schedule.py: usata dal log di stato all'avvio del bot."""

    state = _load_state()
    return {"url": state.get("latest_url"), "lastmod": state.get("latest_lastmod")}


# ==========================================
# SITEMAP
# ==========================================

def _parse_sitemap_xml(body: str) -> dict[str, str]:
    """Estrae {url: lastmod} per le sole pagine
    'banned-and-restricted-*' sotto /en/news/announcements/. Separata dal
    fetch HTTP per essere testabile senza mockare aiohttp."""

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
        if not _BAN_ANNOUNCEMENT_URL_RE.match(loc):
            continue

        found[loc] = lastmod_el.text.strip() if lastmod_el is not None and lastmod_el.text else ""

    return found


async def _fetch_sitemap_ban_urls(session: aiohttp.ClientSession) -> dict[str, str]:
    """Scarica il sitemap e restituisce {url: lastmod} per le sole pagine
    'banned-and-restricted-*' sotto /en/news/announcements/."""

    body = await fetch_sitemap_xml(session)
    if body is None:
        return {}

    return _parse_sitemap_xml(body)


# ==========================================
# PARSING PAGINA ANNUNCIO
# ==========================================

def _strip_tags(text: str) -> str:
    return html_module.unescape(_TAG_RE.sub("", text)).strip()


def parse_ban_announcement(page_html: str) -> dict[str, list[str]] | None:
    """Estrae {formato: [voci di cambiamento]} dal riepilogo di ogni sezione
    <h2>Formato</h2> di un annuncio Banned and Restricted. I formati senza
    modifiche ("No changes") vengono esclusi dal risultato - un dict vuoto
    e' quindi un esito valido (nessun formato toccato in questo giro), non
    un errore. Restituisce None solo se non si trova nemmeno un riepilogo
    strutturato (drift del sito) - il chiamante deve trattarlo come "non
    interpretabile", non come "nessuna modifica"."""

    headings = list(_H2_RE.finditer(page_html))
    if not headings:
        return None

    changes: dict[str, list[str]] = {}
    found_any_summary = False

    for i, heading in enumerate(headings):
        format_name = html_module.unescape(heading.group(1)).strip()
        start = heading.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(page_html)
        chunk = page_html[start:end]

        summary_match = _SUMMARY_P_RE.search(chunk)
        if not summary_match:
            continue
        found_any_summary = True

        lines = [_strip_tags(part) for part in _BR_RE.split(summary_match.group(1))]
        lines = [line for line in lines if line]

        if not lines or (len(lines) == 1 and lines[0].lower() == "no changes"):
            continue

        changes[format_name] = lines

    if not found_any_summary:
        return None

    return changes


def format_lastmod(lastmod: str) -> str:
    """Formatta in italiano il timestamp ISO-8601 del sitemap (es.
    '2026-08-21T18:02:33.573Z' -> '21 Agosto 2026, 18:02 UTC'). E' l'unico
    dato data+ora disponibile per l'annuncio: la pagina mostra un <time> con
    solo il giorno (es. 'Aug 10, 2026'), senza orario, e comunque riflette
    l'ultima modifica della pagina secondo Wizards, non necessariamente
    l'istante di prima pubblicazione. Ritorna la stringa originale invariata
    se il formato non è quello atteso, invece di far fallire la notifica per
    un dettaglio cosmetico."""

    try:
        dt = datetime.fromisoformat(lastmod.replace("Z", "+00:00"))
    except ValueError:
        return lastmod

    return f"{dt.day} {MONTHS_IT[dt.month]} {dt.year}, {dt.strftime('%H:%M')} UTC"


# Stessa selezione per lastmod piu' recente di arena_event_schedule.py -
# vedi pick_latest_by_lastmod() in utils/sitemap_monitor.py.
_pick_latest = pick_latest_by_lastmod


async def _fetch_page_html(session: aiohttp.ClientSession, url: str) -> str | None:
    return await fetch_page_html(session, url, log_prefix="BAN ANNOUNCEMENT")


# ==========================================
# CHECK (API pubblica)
# ==========================================

async def check_ban_announcement_updates(force: bool = False) -> list[dict]:
    """Individua l'annuncio Banned and Restricted PIU' RECENTE (per lastmod)
    sul sitemap e, se e' nuovo rispetto all'ultimo noto (o comunque se
    force=True), lo scarica e prova a interpretarne il riepilogo per
    formato. Gli annunci passati ancora presenti sul sitemap vengono
    ignorati (vedi _pick_latest).

    Ritorna una lista con zero o un elemento {url, lastmod, changes}
    (changes None se il parsing e' fallito, {} se interpretato ma senza
    formati modificati) - la forma a lista resta per coerenza con
    check_event_schedule_updates(). Aggiorna e salva lo stato solo se la
    pagina e' stata effettivamente processata in questa chiamata.
    """

    headers = {"User-Agent": "ClepshydraBot/1.0 (Discord Tournament Bot)"}
    timeout = aiohttp.ClientTimeout(total=60)

    state = _load_state()

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        current = await _fetch_sitemap_ban_urls(session)

        latest = _pick_latest(current)
        if latest is None:
            print("[BAN ANNOUNCEMENT] nessun annuncio trovato sul sitemap")
            return []

        url, lastmod = latest

        already_seen = (
            state.get("latest_url") == url
            and state.get("latest_lastmod") == lastmod
        )
        if already_seen and not force:
            print(f"[BAN ANNOUNCEMENT] nessun cambiamento (piu' recente: {url})")
            return []

        print(f"[BAN ANNOUNCEMENT] annuncio nuovo/aggiornato: {url}")

        page_html = await _fetch_page_html(session, url)

        if page_html is None:
            # Fetch fallito: non aggiorniamo lo stato, ci riproviamo al
            # prossimo giro invece di marcarlo come visto.
            print(f"[BAN ANNOUNCEMENT] fetch fallito per {url}, ritento al prossimo giro")
            return []

        changes = parse_ban_announcement(page_html)

    _save_state({"latest_url": url, "latest_lastmod": lastmod})

    if changes is None:
        print(f"[BAN ANNOUNCEMENT] {url}: struttura riepilogo non riconosciuta")
    else:
        print(f"[BAN ANNOUNCEMENT] {url}: {len(changes)} formati con modifiche")

    return [{"url": url, "lastmod": lastmod, "changes": changes}]


async def periodic_ban_announcement_check_loop(
    bot=None,
    interval_seconds: int = _CHECK_INTERVAL_SECONDS,
) -> None:
    """Task in background: controlla quotidianamente il sitemap e notifica su
    Discord ogni nuovo annuncio Banned and Restricted. Il primo giro parte
    subito all'avvio, come gli altri periodic_*_loop di main.py."""

    while True:
        try:
            results = await check_ban_announcement_updates()

            if results and bot is not None:
                logger = bot.get_cog("Logger")
                if logger:
                    for result in results:
                        await send_ban_announcement_log(logger, result, user=None, forced=False)

        except Exception as e:
            print(f"[BAN ANNOUNCEMENT AUTO-CHECK] errore: {e}")

        await asyncio.sleep(interval_seconds)


_FIELD_VALUE_LIMIT = 1024  # limite Discord per il valore di un campo embed


async def send_ban_announcement_log(logger, result: dict, user, forced: bool) -> None:
    """Posta su Discord (via Logger cog) l'esito del controllo di un singolo
    annuncio Banned and Restricted. Esposta come funzione pubblica perche'
    usata sia dal loop automatico sia dal comando admin manuale.

    Solo notifica: non scrive mai su banned_cards (vedi docs/banlist-system.md
    - nessuno dei formati ufficiali Wizards in questi annunci corrisponde
    all'Artisan homebrew di questa community, quindi non c'e' un messaggio
    da comunicare a riguardo). Quando l'annuncio contiene modifiche reali,
    l'embed viene postato anche in COMUNICATION_CHANNEL_ID (import differito,
    come utils/permissions.py, per restare importabile nei test senza un
    .env completo) oltre che nel canale log - riguarda tutta la community,
    non solo lo staff. Il canale community e' un canale pubblico dove si fa
    anche @everyone: usa `community_title`/`community_info` di
    Logger.send_log() per un embed dedicato senza il gergo da staff
    ("Controllo manuale forzato", l'utente che ha invocato il comando) che
    invece resta nell'`info` del canale log - solo i `fields` (le carte
    bannate/sbannate per formato) sono condivisi tra i due, sono contenuto
    genuino anche per la community."""

    url = result["url"]
    changes = result["changes"]
    prefix = "Controllo manuale forzato" if forced else "Controllo automatico"

    if changes is None:
        await logger.send_log(
            level="WARN",
            event="BAN_ANNOUNCEMENT_UNPARSEABLE",
            user=user,
            info=(
                f"{prefix}: trovato un nuovo Banned and Restricted Announcement su {url} ma "
                f"il riepilogo per formato non e' stato riconosciuto (possibile cambio di "
                f"struttura del sito). Controllo manuale consigliato."
            ),
        )
        return

    if not changes:
        await logger.send_log(
            level="INFO",
            event="BAN_ANNOUNCEMENT_NO_CHANGES",
            user=user,
            info=(
                f"{prefix}: nuovo Banned and Restricted Announcement su {url}, nessun formato "
                f"modificato in questo giro."
            ),
        )
        return

    fields = []
    for format_name, lines in changes.items():
        value = "\n".join(lines)
        if len(value) > _FIELD_VALUE_LIMIT:
            value = value[: _FIELD_VALUE_LIMIT - 1] + "…"
        fields.append({"name": format_name, "value": value, "inline": False})

    from config.config import COMUNICATION_CHANNEL_ID

    lastmod_text = format_lastmod(result["lastmod"])

    await logger.send_log(
        level="INFO",
        event="BAN_ANNOUNCEMENT_UPDATED",
        user=user,
        info=f"{prefix}: nuovo Banned and Restricted Announcement — {url}",
        fields=fields,
        extra_channel_id=COMUNICATION_CHANNEL_ID,
        community_title=f"📋 Nuovo Banned and Restricted Announcement — {lastmod_text}",
        community_info=f"Ecco cosa cambia nei formati ufficiali Magic — [leggi l'annuncio completo]({url})",
    )
