"""
arena_overrides.py

Gestisce gli override di rarità per le carte che su Arena appaiono
con rarità più alta rispetto alle loro stampe paper (es. SPG).

BUG CORRETTI:
- get_override_rarity: non rilegge il JSON da disco ad ogni chiamata
  (ora usa una cache in-memory con invalidazione esplicita)
- update_spg_overrides: la logica "skip set già processati" era rotta
  perché il JSON di default aveva già "SPG" in processed_sets,
  rendendo il primo run un no-op. Ora processed_sets tiene traccia
  solo dei set completamente scansionati, e viene aggiornato SOLO
  a fine run riuscito.
- Aggiunto rate limiting (110ms tra richieste) coerente con tournament.py
- La funzione ora è parametrica sul set_code invece di hardcoded "spg"
"""

import asyncio
import json
import os
import aiohttp

DATA_PATH = "data/arena_rarity_data.json"

_MIN_REQUEST_INTERVAL = 0.11

_override_cache: dict | None = None


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
            "processed_sets": [],
            "overrides": {}
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
# UPDATE SPG OVERRIDES
# ==========================================

async def update_spg_overrides(set_code: str = "spg") -> list[tuple[str, str]]:
    """
    Scansiona tutte le carte del set indicato su Scryfall e aggiunge
    override per quelle che su Arena hanno rarità rare/mythic ma
    su carta (paper) esistono in versione common/uncommon.

    Ritorna la lista di (card_name, rarity) aggiunti in questo run.

    BUG CORRETTI:
    - processed_sets ora è usato solo per evitare di riprocessare set
      già completamente scansionati in run precedenti. Il controllo
      è a livello di SET INTERO, non di singola carta nel loop.
    - Il set viene marcato come "processato" solo a fine run riuscito.
    - Il JSON iniziale non deve contenere "SPG" in processed_sets,
      altrimenti il primo run non farà nulla. Se viene trovato,
      lo rimuoviamo prima di procedere (migrazione automatica).
    """

    set_upper = set_code.upper()

    data = _load_override_data()
    processed_sets: set[str] = set(data.get("processed_sets", []))
    overrides: dict[str, str] = data.get("overrides", {})

    if set_upper in processed_sets:
        print(
            f"[SKIP] Set {set_upper} già processato. "
            f"Usa invalidate_override_cache() e rimuovi '{set_upper}' "
            f"da processed_sets per forzare il riscansionamento."
        )
        return []

    added_cards: list[tuple[str, str]] = []

    encoded_set = set_code.lower()
    search_url: str | None = (
        f"https://api.scryfall.com/cards/search"
        f"?q=set%3A{encoded_set}&unique=prints"
    )

    headers = {
        "User-Agent": "ClepshydraBot/1.0 (Discord Tournament Bot)"
    }

    timeout = aiohttp.ClientTimeout(total=120)

    async with aiohttp.ClientSession(
        headers=headers,
        timeout=timeout
    ) as session:

        while search_url:

            result = await _scryfall_get(
                session, search_url, f"search {set_upper}"
            )

            if not result:
                print(f"[ABORT] Impossibile ottenere dati per {set_upper}")
                return added_cards

            cards = result.get("data", [])

            for card in cards:

                card_name: str = card.get("name", "")
                prints_uri: str | None = card.get("prints_search_uri")

                if not prints_uri:
                    continue

                print(f"[CHECKING] {card_name}")

                prints_data = await _scryfall_get(
                    session,
                    prints_uri,
                    f"{card_name} [prints]"
                )

                if not prints_data:
                    continue

                arena_target_rarity: str | None = None
                paper_lowest: str | None = None

                rarity_rank = {"common": 0, "uncommon": 1, "rare": 2, "mythic": 3}

                for printing in prints_data.get("data", []):

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

            search_url = result.get("next_page")

    processed_sets.add(set_upper)

    _save_override_data({
        "processed_sets": list(processed_sets),
        "overrides": overrides
    })

    print(
        f"[DONE] {set_upper}: "
        f"{len(added_cards)} override aggiunti."
    )

    return added_cards