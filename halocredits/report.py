import csv
from pathlib import Path

from .models import ParseResult


def write_audit_logs(result: ParseResult, logs_dir: Path) -> None:
    logs_dir = Path(logs_dir)
    (logs_dir / "dropped").mkdir(parents=True, exist_ok=True)
    (logs_dir / "unparsed").mkdir(parents=True, exist_ok=True)

    with open(logs_dir / "dropped" / f"{result.game_id}.txt", "w",
              encoding="utf-8", newline="\n") as fh:
        for line, reason in result.dropped:
            fh.write(f"{line}\t{reason}\n")

    with open(logs_dir / "unparsed" / f"{result.game_id}.txt", "w",
              encoding="utf-8", newline="\n") as fh:
        for line, ref in result.unparsed:
            fh.write(f"{ref}\t{line}\n")


class ParseReport:
    def __init__(self) -> None:
        self.entries: list[tuple[str, int, int, int]] = []

    def add(self, result: ParseResult) -> None:
        self.entries.append(
            (result.game_id, len(result.rows), len(result.dropped), len(result.unparsed))
        )

    def write(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="\n", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["game_id", "rows", "dropped", "unparsed"])
            w.writerows(self.entries)

    def failures(self, threshold: float) -> list[str]:
        bad = []
        for game_id, rows, _dropped, unparsed in self.entries:
            if rows == 0:
                bad.append(game_id)
                continue
            if unparsed / (rows + unparsed) > threshold:
                bad.append(game_id)
        return bad

    def render(self) -> str:
        lines = [f"{'game':24s} {'rows':>6s} {'dropped':>8s} {'unparsed':>9s}"]
        for game_id, rows, dropped, unparsed in self.entries:
            lines.append(f"{game_id:24s} {rows:6d} {dropped:8d} {unparsed:9d}")
        return "\n".join(lines)
