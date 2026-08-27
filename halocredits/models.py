from dataclasses import dataclass, field
from enum import Enum

CSV_COLUMNS = [
    "game_id", "credit_order", "name_raw", "name_canonical",
    "category", "role_raw", "character", "studio",
    "inclusion_class", "source_ref",
]


class InclusionClass(str, Enum):
    CORE = "core"
    PUBLISHING = "publishing"
    SPECIAL_THANKS = "special-thanks"
    BABIES = "babies"
    LEGACY = "legacy"
    # Volunteers credited alongside staff but never employed on the game:
    # MCC's "Reclaimers" modding programme and Campaign Evolved's "Sentinels".
    # They appear in exactly one game by construction, so counting them as core
    # would inflate newcomers and one-and-done departures - the same distortion
    # the English-only voice rule exists to prevent.
    COMMUNITY = "community"


@dataclass
class CreditRow:
    game_id: str
    credit_order: int
    name_raw: str
    name_canonical: str = ""
    category: str = "Other"
    role_raw: str = ""
    character: str = ""
    studio: str = ""
    inclusion_class: InclusionClass = InclusionClass.CORE
    source_ref: str = ""

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "credit_order": self.credit_order,
            "name_raw": self.name_raw,
            "name_canonical": self.name_canonical,
            "category": self.category,
            "role_raw": self.role_raw,
            "character": self.character,
            "studio": self.studio,
            "inclusion_class": self.inclusion_class.value,
            "source_ref": self.source_ref,
        }


@dataclass
class ParseResult:
    game_id: str
    rows: list[CreditRow] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)
    unparsed: list[tuple[str, str]] = field(default_factory=list)

    def add(self, row: CreditRow) -> None:
        self.rows.append(row)

    def drop(self, line: str, reason: str) -> None:
        self.dropped.append((line, reason))

    def fail(self, line: str, source_ref: str) -> None:
        self.unparsed.append((line, source_ref))
