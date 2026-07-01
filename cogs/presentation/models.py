from dataclasses import dataclass, field
from typing import Optional


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