import csv
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GameConfig:
    game_id: str
    title: str
    year: int
    sequence: int
    type: str


@dataclass
class SourceConfig:
    game_id: str
    parser: str
    url: str
    raw_path: str
    options: dict = field(default_factory=dict)


def load_games(path: Path) -> dict[str, GameConfig]:
    out: dict[str, GameConfig] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[r["game_id"]] = GameConfig(
                game_id=r["game_id"],
                title=r["title"],
                year=int(r["year"]),
                sequence=int(r["sequence"]),
                type=r["type"],
            )
    return out


def load_sources(path: Path) -> dict[str, SourceConfig]:
    out: dict[str, SourceConfig] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[r["game_id"]] = SourceConfig(
                game_id=r["game_id"],
                parser=r["parser"],
                url=r["url"],
                raw_path=r["raw_path"],
                options=json.loads(r["options"] or "{}"),
            )
    return out
