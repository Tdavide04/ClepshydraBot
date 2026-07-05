from dataclasses import dataclass, field
from typing import Optional

# Storage temporaneo per i dati di presentazione tra le interazioni
PRESENTATION_DATA_STORE: dict[int, 'PresentationData'] = {}


def get_presentation_data(user_id: int) -> Optional['PresentationData']:
    return PRESENTATION_DATA_STORE.get(user_id)


def store_presentation_data(user_id: int, data: 'PresentationData') -> None:
    PRESENTATION_DATA_STORE[user_id] = data


async def get_or_create_presentation_data(user_id: int) -> 'PresentationData':
    if user_id not in PRESENTATION_DATA_STORE:
        PRESENTATION_DATA_STORE[user_id] = PresentationData(
            user_id=user_id,
            nome="",
            nickname_arena="",
            anno_nascita="",
            professione="",
            provenienza="",
            anno_cartaceo="",
            anno_arena=""
        )
    return PRESENTATION_DATA_STORE[user_id]


@dataclass
class PresentationData:
    user_id: int
    nome: str
    nickname_arena: str
    anno_nascita: str
    professione: str
    provenienza: str

    anno_cartaceo: str
    anno_arena: str

    colori: list[str] = field(default_factory=list)
    gilde: list[str] = field(default_factory=list)
    formati_construed: list[str] = field(default_factory=list)
    formati_limited: list[str] = field(default_factory=list)

    risultati: str = ""
    passioni: str = ""

    @property
    def formati_preferiti(self) -> list[str]:
        combined = list(self.formati_construed) + list(self.formati_limited)
        if "Nessuno" in combined:
            return ["Nessuno"]
        if "N/A" in combined and len(combined) == 1:
            return ["N/A"]
        return [f for f in combined if f not in ("Nessuno", "N/A")]

    @property
    def formati_preferiti_raw(self) -> str:
        return ", ".join(self.formati_preferiti)

    @property
    def colori_raw(self) -> str:
        return ", ".join(self.colori) if self.colori else "Nessuno"

    @property
    def gilde_raw(self) -> str:
        return ", ".join(self.gilde) if self.gilde else "Nessuno"