"""
arena_overrides.py

Gestisce gli override di rarità per le carte che su Arena appaiono
con rarità più alta rispetto alle loro stampe paper (es. SPG).

BUG CORRETTI (Settembre 2026, vedi docs/roadmap-miglioramenti.md):
- update_spg_overrides usava processed_sets per marcare un intero set come
  "fatto per sempre" dopo la prima scansione riuscita. Sbagliato per SPG:
  Scryfall usa un unico set code "SPG" che cresce continuamente nel tempo
  (nuove Special Guests escono con quasi ogni set principale, ogni 4-8
  settimane) - dopo la prima scansione, ogni run successivo (anche manuale)
  diventava un no-op permanente, senza alcun modo di sbloccarlo se non
  editando il JSON a mano. Sostituito con checked_cards: un elenco per set
  code delle singole carte già valutate (aggiunto override o no). Una nuova
  scansione salta solo le carte già viste, non l'intero set - i run
  successivi al primo costano solo le carte nuove dall'ultimo controllo,
  rendendo sicuro schedularli periodicamente (vedi periodic_spg_refresh_loop).
- _update_lock: la funzione ora gira sia da un comando admin manuale sia da
  un task periodico automatico - un lock evita che due scansioni concorrenti
  si sovrascrivano a vicenda sul JSON.

BATCHING (Settembre 2026): update_spg_overrides faceva una richiesta
prints_search_uri per OGNI carta non ancora valutata (pattern N+1). Innocuo
per i run incrementali (poche carte nuove a settimana), ma il primo run dopo
la migrazione da processed_sets a checked_cards deve ricontrollare l'intero
set in un colpo solo (centinaia di carte) - osservato in produzione: decine
di 429 consecutivi, ogni scan rallentato dal backoff esponenziale. Sostituito
con _fetch_prints_by_oracle_ids: una query combinata (`oracleid:X or
oracleid:Y or ...`) per gruppi di _PRINTS_BATCH_SIZE carte, che restituisce
tutte le stampe di piu' carte in una sola chiamata (paginata se necessario).
"""

import asyncio
import json
import os
from urllib.parse import quote

import aiohttp

DATA_PATH = "data/arena_rarity_data.json"

_MIN_REQUEST_INTERVAL = 0.11

# Quante carte per query combinata in _fetch_prints_by_oracle_ids. Piu' alto
# riduce il numero di richieste ma allunga la query (e le pagine di risultati
# da scaricare, essendo la somma delle stampe di tutte le carte nel batch);
# 25 e' un compromesso prudente, ben sotto i limiti di lunghezza URL e senza
# rischiare risposte multi-pagina enormi per un singolo batch.
_PRINTS_BATCH_SIZE = 25

# Nuove Special Guests escono con quasi ogni set principale (~4-8 settimane in
# media, vedi ricerca in docs/roadmap-miglioramenti.md). Settimanale da ampio
# margine: dopo il primo giro, un controllo costa solo le carte nuove
# dall'ultimo run (grazie a checked_cards), quindi anche se non cambia mai
# nulla il costo di un giro a vuoto è trascurabile.
_SPG_REFRESH_INTERVAL_SECONDS = 7 * 24 * 60 * 60

_override_cache: dict | None = None
_update_lock = asyncio.Lock()


# ==========================================
# LOAD / SAVE
# ==========================================

def _load_override_data() -> dict:
    """Carica il JSON. Usa cache in-memory, rilegge solo se necessario."""

    global _override_cache

    if _override_cache is not None:
        return _override_cache

    if not os.path.exists(DATA_PATH):
        _override_cache = {
            "overrides": {},
            "checked_cards": {},
        }
        return _override_cache

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        _override_cache = json.load(f)

    return _override_cache


def _save_override_data(data: dict) -> None:
    """Salva il JSON e aggiorna la cache in-memory."""

    global _override_cache

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    _override_cache = data


def invalidate_override_cache() -> None:
    """Forza il ricaricamento del JSON alla prossima lettura."""

    global _override_cache
    _override_cache = None


# ==========================================
# GET OVERRIDE (API pubblica)
# ==========================================

def get_override_rarity(card_name: str) -> str | None:
    """
    Restituisce la rarità di override per una carta, o None se non presente.
    Usa cache in-memory: nessuna lettura da disco per chiamate ripetute.
    """

    data = _load_override_data()
    return data.get("overrides", {}).get(card_name)


# ==========================================
# SCRYFALL HELPER
# ==========================================

async def _scryfall_get(
    session: aiohttp.ClientSession,
    url: str,
    label: str,
    retries: int = 5
) -> dict | None:
    """
    GET verso Scryfall con backoff esponenziale su 429.
    Condivide la stessa politica di rate limit di tournament.py.
    """

    for attempt in range(retries):

        try:

            async with session.get(url) as response:

                if response.status == 429:

                    retry_after = response.headers.get("Retry-After")
                    wait_time = float(retry_after) if retry_after else 2 ** attempt

                    print(
                        f"[429] {label} -> "
                        f"retry tra {wait_time:.1f}s "
                        f"(attempt {attempt + 1}/{retries})"
                    )

                    await asyncio.sleep(wait_time)
                    continue

                if response.status != 200:
                    print(
                        f"[SCRYFALL FAIL] {label} -> {response.status}"
                    )
                    return None

                data = await response.json()

                # Delay minimo dopo ogni risposta 200
                await asyncio.sleep(_MIN_REQUEST_INTERVAL)

                return data

        except asyncio.TimeoutError:

            print(
                f"[TIMEOUT] {label} "
                f"(attempt {attempt + 1}/{retries})"
            )
            await asyncio.sleep(2 ** attempt)

        except Exception as e:

            print(f"[SCRYFALL ERROR] {label}: {e}")
            return None

    print(f"[EXHAUSTED] {label}: tutti i retry falliti")
    return None


# ==========================================
# BATCH PRINTS FETCH
# ==========================================

async def _fetch_prints_by_oracle_ids(
    session: aiohttp.ClientSession,
    oracle_ids: list[str],
) -> dict[str, list[dict]]:
    """Recupera TUTTE le stampe di piu' carte in una sola query combinata
    (`oracleid:X or oracleid:Y or ...`, paginata se il gruppo ne produce piu'
    di una pagina), invece di una prints_search_uri per carta. Ritorna
    {oracle_id: [printing, ...]}; un oracle_id assente dal dict o con lista
    vuota significa che la query e' fallita per l'intero batch (il chiamante
    deve trattarlo come 'da riprovare', non come 'nessuna stampa')."""

    if not oracle_ids:
        return {}

    # Deduplicare e' necessario, non solo un'ottimizzazione: verificato dal
    # vivo che una query con oracleid ripetuti (`oracleid:X or oracleid:X`,
    # che capita sempre - la ricerca 'set:spg unique=prints' a monte elenca
    # una riga per stampa, quindi una carta con piu' stampe SPG appare piu'
    # volte) fa tornare a Scryfall risultati INCOMPLETI (alcune carte
    # mancanti dal risultato, silenziosamente) invece di un errore esplicito.
    unique_oracle_ids = list(dict.fromkeys(oracle_ids))

    query = " or ".join(f"oracleid:{oid}" for oid in unique_oracle_ids)
    search_url: str | None = (
        f"https://api.scryfall.com/cards/search?q={quote(query)}&unique=prints"
    )

    grouped: dict[str, list[dict]] = {}

    while search_url:
        result = await _scryfall_get(
            session, search_url, f"prints batch ({len(oracle_ids)} carte)"
        )

        if not result:
            # Batch fallito: nessuna carta del gruppo va segnata come
            # controllata, ci si riprova tutte insieme al prossimo giro.
            return {}

        for printing in result.get("data", []):
            oid = printing.get("oracle_id")
            if oid:
                grouped.setdefault(oid, []).append(printing)

        search_url = result.get("next_page")

    return grouped


# ==========================================
# UPDATE SPG OVERRIDES
# ==========================================

async def update_spg_overrides(set_code: str = "spg") -> list[tuple[str, str]]:
    """
    Scansiona le carte NON ANCORA VALUTATE del set indicato su Scryfall e
    aggiunge override per quelle che su Arena hanno rarità rare/mythic ma
    su carta (paper) esistono in versione common/uncommon.

    Incrementale per design: ogni carta valutata (con o senza override
    aggiunto) viene registrata in checked_cards[set_code] e non viene più
    ri-scaricata nei run successivi. Sicuro da chiamare ripetutamente (da un
    comando admin o da un task periodico): il primo run su un set paga il
    costo pieno, i successivi costano solo le carte apparse nel frattempo.
    Le stampe delle carte non valutate vengono recuperate in batch
    (_fetch_prints_by_oracle_ids, gruppi di _PRINTS_BATCH_SIZE), non una
    richiesta per carta.

    Ritorna la lista di (card_name, rarity) aggiunti in QUESTO run (non
    l'intero storico).
    """

    async with _update_lock:
        set_upper = set_code.upper()

        data = _load_override_data()
        overrides: dict[str, str] = data.get("overrides", {})
        checked_by_set: dict[str, list[str]] = data.get("checked_cards", {})
        checked: set[str] = set(checked_by_set.get(set_upper, []))

        added_cards: list[tuple[str, str]] = []
        newly_checked: list[str] = []

        def _persist() -> None:
            checked_by_set[set_upper] = sorted(checked | set(newly_checked))
            _save_override_data({
                "overrides": overrides,
                "checked_cards": checked_by_set,
            })

        encoded_set = set_code.lower()
        search_url: str | None = (
            f"https://api.scryfall.com/cards/search"
            f"?q=set%3A{encoded_set}&unique=prints"
        )

        headers = {
            "User-Agent": "ClepshydraBot/1.0 (Discord Tournament Bot)"
        }

        timeout = aiohttp.ClientTimeout(total=120)

        rarity_rank = {"common": 0, "uncommon": 1, "rare": 2, "mythic": 3}

        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout
        ) as session:

            # 1. Elenca tutte le carte del set (nome + oracle_id), paginando.
            unchecked: list[tuple[str, str | None]] = []

            while search_url:

                result = await _scryfall_get(
                    session, search_url, f"search {set_upper}"
                )

                if not result:
                    print(f"[ABORT] Impossibile ottenere dati per {set_upper}")
                    _persist()
                    return added_cards

                for card in result.get("data", []):
                    card_name: str = card.get("name", "")
                    if card_name and card_name not in checked:
                        unchecked.append((card_name, card.get("oracle_id")))

                search_url = result.get("next_page")

            print(f"[{set_upper}] {len(unchecked)} carte da valutare")

            # 2. Recupera le stampe delle carte non valutate in batch.
            oracle_ids = [oid for _, oid in unchecked if oid]
            prints_by_oracle: dict[str, list[dict]] = {}

            for batch_start in range(0, len(oracle_ids), _PRINTS_BATCH_SIZE):
                batch = oracle_ids[batch_start:batch_start + _PRINTS_BATCH_SIZE]
                print(f"[BATCH] {batch_start + 1}-{batch_start + len(batch)} di {len(oracle_ids)}")
                prints_by_oracle.update(
                    await _fetch_prints_by_oracle_ids(session, batch)
                )

            # 3. Valuta ogni carta con le stampe recuperate al passo 2.
            for card_name, oracle_id in unchecked:

                printings = prints_by_oracle.get(oracle_id) if oracle_id else None

                if not printings:
                    # Nessuna stampa recuperata (oracle_id mancante o batch
                    # fallito): non segnarla come controllata, ci si riprova
                    # al prossimo giro invece di perderla per sempre.
                    continue

                arena_target_rarity: str | None = None
                paper_lowest: str | None = None

                for printing in printings:

                    games: list = printing.get("games", [])
                    rarity: str = printing.get("rarity", "").lower()
                    printing_set: str = printing.get("set", "").lower()

                    if "arena" in games and printing_set == set_code.lower():
                        arena_target_rarity = rarity

                    if "paper" in games and rarity in rarity_rank:
                        if (
                            paper_lowest is None
                            or rarity_rank[rarity] < rarity_rank[paper_lowest]
                        ):
                            paper_lowest = rarity

                            if paper_lowest == "common":
                                break

                if (
                    arena_target_rarity in ("rare", "mythic")
                    and paper_lowest in ("common", "uncommon")
                    and card_name not in overrides
                ):

                    print(
                        f"[OVERRIDE ADDED] "
                        f"{card_name} -> {paper_lowest} "
                        f"(Arena: {arena_target_rarity})"
                    )

                    overrides[card_name] = paper_lowest
                    added_cards.append((card_name, paper_lowest))

                newly_checked.append(card_name)

        _persist()

        print(
            f"[DONE] {set_upper}: "
            f"{len(added_cards)} nuovi override, "
            f"{len(newly_checked)} carte controllate in questo giro."
        )

        return added_cards


async def periodic_spg_refresh_loop(bot=None, interval_seconds: int = _SPG_REFRESH_INTERVAL_SECONDS) -> None:
    """Task in background: ricontrolla il set SPG a intervalli regolari senza
    bisogno che un admin lanci il comando manuale. Il primo giro parte subito
    all'avvio (non aspetta il primo intervallo) così eventuali carte nuove
    vengono recuperate appena il bot riparte, non solo una volta a settimana."""
    while True:
        try:
            added = await update_spg_overrides(set_code="spg")
            if added and bot is not None:
                logger = bot.get_cog("Logger")
                if logger:
                    lines = "\n".join(f"• **{name}** → {rarity}" for name, rarity in added[:20])
                    await logger.send_log(
                        level="INFO",
                        event="SPG_OVERRIDES_UPDATED",
                        info=f"Controllo automatico: {len(added)} nuovi override trovati\n\n{lines}",
                    )
        except Exception as e:
            print(f"[SPG AUTO-REFRESH] errore: {e}")

        await asyncio.sleep(interval_seconds)
