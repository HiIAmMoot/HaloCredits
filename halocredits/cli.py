import argparse
import csv
import sys
from pathlib import Path

from .config import load_games, load_sources
from .fetch import freeze
from .inclusionfix import apply_inclusion_overrides, load_inclusion_overrides
from .identity import (Person, load_aliases, load_credit_rows, load_reviews,
                        resolve, write_uncertain_review)
from .lineage import lineage, write_lineage
from .mobygames_additions import apply_mobygames_additions, load_mobygames_additions
from .namefix import apply_name_fixes, load_name_fixes
from .normalize import load_category_map, load_non_person_patterns
from .parsers import PARSERS
from .report import ParseReport, write_audit_logs
from .stats import flows, per_game_stats, write_flows, write_per_game
from .studiofix import apply_studio_fixes, load_studio_fixes
from .studios import load_studio_classes
from .writer import write_credits


def run_fetch(root: Path) -> None:
    for source in load_sources(root / "config" / "sources.csv").values():
        path = freeze(source, root)
        print(f"{source.game_id:24s} -> {path or 'skipped (manual source)'}")


def run_all(root: Path) -> ParseReport:
    root = Path(root)
    games = load_games(root / "config" / "games.csv")
    sources = load_sources(root / "config" / "sources.csv")
    cats = load_category_map(root / "config" / "category-map.csv")
    nonp = load_non_person_patterns(root / "config" / "non-person-patterns.txt")
    fixes = load_name_fixes(root / "config" / "name-fixes.csv")
    studio_fixes = load_studio_fixes(root / "config" / "studio-fixes.csv")
    mobygames_additions = load_mobygames_additions(root / "config" / "mobygames-additions")
    inclusion_overrides = load_inclusion_overrides(root / "config" / "inclusion-overrides.csv")

    report = ParseReport()
    discarded = extracted = studio_fixed = added = reclassed = 0
    for game_id in sorted(games, key=lambda g: games[g].sequence):
        source = sources[game_id]
        parser = PARSERS[source.parser]
        text = (root / source.raw_path).read_text(encoding="utf-8")
        result = parser(text, game_id, source.options, cats, nonp)
        # Hand-ruled corrections run before anything is written, so the credit
        # CSVs and every stage downstream of them see corrected data.
        d, e = apply_name_fixes(result, fixes)
        discarded += d
        extracted += e
        studio_fixed += apply_studio_fixes(result, studio_fixes)
        added += apply_mobygames_additions(result, mobygames_additions)
        reclassed += apply_inclusion_overrides(result, inclusion_overrides)
        write_credits(result, root / "data" / "credits")
        write_audit_logs(result, root / "logs")
        report.add(result)

    if studio_fixes:
        print(f"studio fixes: {studio_fixed} rows corrected")
    if fixes:
        print(f"name fixes: {discarded} rows discarded, {extracted} names extracted")
    if mobygames_additions:
        print(f"mobygames additions: {added} rows appended")
    if inclusion_overrides:
        print(f"inclusion overrides: {reclassed} rows reclassified")
    report.write(root / "logs" / "parse-report.csv")
    return report


def write_people(people: dict[str, Person], path: Path) -> Path:
    """The registry from design spec §4, one row per resolved person.

    `variants` and `games` are `|`-joined rather than comma-joined: both are
    lists that can themselves contain commas (a credited name can, a game
    list never does today but joining consistently costs nothing), and the
    file is CSV.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["person_id", "display_name", "variants", "first_game",
                    "last_game", "game_count", "games", "span_years",
                    "largest_gap_years", "uncertain"])
        for p in sorted(people.values(), key=lambda p: p.person_id):
            w.writerow([p.person_id, p.display_name, "|".join(p.variants),
                        p.first_game, p.last_game, p.game_count,
                        "|".join(p.games), p.span_years,
                        p.largest_gap_years, p.uncertain])
    return path


def run_people(root: Path) -> int:
    root = Path(root)
    games = load_games(root / "config" / "games.csv")
    rows = load_credit_rows(root / "data" / "credits")
    aliases = load_aliases(root / "config" / "aliases.csv")
    reviews = load_reviews(root / "config" / "identity-review.csv")
    people = resolve(rows, games, aliases, reviews)
    write_people(people, root / "data" / "people.csv")
    flagged = write_uncertain_review(people, root / "review" / "uncertain.csv")
    print(f"{len(people)} people, {flagged} flagged for review")
    return len(people)


def run_stats(root: Path) -> None:
    root = Path(root)
    games = load_games(root / "config" / "games.csv")
    classes = load_studio_classes(root / "config" / "studio-classes.csv")
    rows = load_credit_rows(root / "data" / "credits")
    people = resolve(rows, games,
                     load_aliases(root / "config" / "aliases.csv"),
                     load_reviews(root / "config" / "identity-review.csv"))
    out = root / "data" / "stats"
    write_per_game(per_game_stats(rows, people, games, classes), out / "per_game.csv")
    write_flows(flows(rows, people, games), out / "flows.csv")
    write_lineage(lineage(rows, people, games, classes)
                  + lineage(rows, people, games, classes, first_party_only=True),
                  out / "lineage.csv")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="halocredits")
    parser.add_argument("command", choices=["fetch", "parse", "people", "stats", "all"])
    parser.add_argument("--root", default=".")
    parser.add_argument("--threshold", type=float, default=0.05)
    args = parser.parse_args(argv)

    root = Path(args.root)
    if args.command in ("fetch", "all"):
        run_fetch(root)
    if args.command in ("parse", "all"):
        report = run_all(root)
        print(report.render())
        bad = report.failures(args.threshold)
        if bad:
            print(f"\nFAILED: unparsed rate above threshold for: {', '.join(bad)}",
                  file=sys.stderr)
            return 1
    if args.command in ("people", "all"):
        run_people(root)
    if args.command in ("stats", "all"):
        run_stats(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
