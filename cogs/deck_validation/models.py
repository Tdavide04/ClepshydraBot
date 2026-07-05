from dataclasses import dataclass, field


@dataclass
class DeckEntry:
    quantity: int
    name: str
    is_sideboard: bool


@dataclass
class ArtisanCard:
    name: str
    quantity: int
    image_url: str | None
    type_line: str
    cmc: float
    is_sideboard: bool

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "quantity": self.quantity,
            "image_url": self.image_url,
            "type_line": self.type_line,
            "cmc": self.cmc,
        }


@dataclass
class DeckValidationResult:
    deck_name: str
    total_cards: int
    main_count: int
    side_count: int
    banned_cards: list[str] = field(default_factory=list)
    invalid_cards: list[str] = field(default_factory=list)
    illegal_rarity_cards: list[str] = field(default_factory=list)
    mainboard: list[ArtisanCard] = field(default_factory=list)
    sideboard: list[ArtisanCard] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return (
            not self.banned_cards
            and not self.invalid_cards
            and not self.illegal_rarity_cards
            and self.main_count >= 60
            and self.side_count <= 15
        )
