from pathlib import Path
from halocredits.studios import classify_studio, load_studio_classes, normalise_studio

ROOT = Path(__file__).resolve().parents[1]
CLASSES = load_studio_classes(ROOT / "config" / "studio-classes.csv")


def test_blank_is_first_party_by_absence():
    assert classify_studio("", CLASSES) == ""


def test_external_vendors_are_vendors():
    for name in ["Experis", "Virtuos Chengdu", "Keywords Studios",
                 "Sperasoft, Inc.", "Behaviour Interactive", "Lionbridge Games"]:
        assert classify_studio(name, CLASSES) == "vendor", name


def test_microsoft_sibling_studios_are_not_first_party():
    """"First-party" means the game's own credited developer -- 343
    Industries, Halo Studios, or Bungie, whichever built that game -- not
    "owned by Microsoft." Rare and Ninja Theory are real, separate studios
    with their own staff and culture; someone credited under them worked
    for Rare, not for Halo Studios, in exactly the sense that someone
    credited under Experis (a staffing agency) did not work for Halo
    Studios either. Classifying either group as first-party would count
    them as the core team when they are not."""
    for name in ["Rare", "Ninja Theory", "Turn 10 Studios", "Xbox Game Studios"]:
        assert classify_studio(name, CLASSES) == "vendor", name


def test_self_described_independents_are_the_inverse_of_an_agency():
    """"Independent" and "FREELANCE" denote the ABSENCE of an employer. A
    classifier treating any non-blank value as a company gets them backwards."""
    assert classify_studio("Independent", CLASSES) == "independent"
    assert classify_studio("FREELANCE", CLASSES) == "independent"


def test_case_variants_resolve_to_one_class():
    """The corpus carries EXPERIS (467 rows) and Experis (422) as separate
    strings. They are one company."""
    assert normalise_studio("EXPERIS") == normalise_studio("Experis")
    assert classify_studio("EXPERIS", CLASSES) == classify_studio("Experis", CLASSES)


def test_unknown_studio_defaults_to_vendor():
    assert classify_studio("Some New Outsourcer Ltd", CLASSES) == "vendor"


def test_real_corpus_class_distribution():
    """Measured over the committed CSVs. Exact, so a reclassification that
    changes contractor share cannot pass unnoticed."""
    import csv, glob
    from collections import Counter
    counts = Counter()
    for path in glob.glob(str(ROOT / "data" / "credits" / "*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                counts[classify_studio(row["studio"], CLASSES)] += 1
    # Counts grew after the MobyGames redo landed (see test_identity.py's
    # DISTINCT_PEOPLE note): 1256 new credit rows across 9 games, the large
    # majority vendor-tagged (Blur, the Skywalker orchestra/chorus, Saber
    # Interactive, Certain Affinity, and dozens of halo-infinite outsource
    # partners).
    # 6475/6806 -> 6588/6894: a follow-up batch of MobyGames duplicate
    # resolutions (candidate matches that were missed in the first review
    # pass) added more credit rows attributed to already-existing people.
    # 6477/6948 -> 6476/6965: halo-mcc's "Halo 2A: Audio - Finishing Move
    # Inc." block. Sixteen of its credits had been rejected in review as
    # duplicates of the same names already in the corpus -- but every one of
    # those names sat on a DIFFERENT game (Brian Trifon and Jillian Aversa on
    # halo-cea, Steve Kaplan on halo-infinite, Steve Vai on halo-2), so they
    # were the same people earning a second credit, not duplicates. Restoring
    # them adds 17 vendor rows; the one blank that disappears is Brian Lee
    # White's "Adapted and Orchestrated By" row, which named the Finishing
    # Move team but carried no studio of its own.
    # 6475/6965 -> 6462/6966: name-fixes.csv discards for fabricated
    # "people" (halo-reach's fake community organisations, halo-4's
    # middleware vendors mislabelled as scanned talent) removed 12 blank-
    # studio rows and one Excell-vendor row surfaced by the Cory Blaksee
    # fix -- see test_identity.py's DISTINCT_PEOPLE note.
    # 6462/6966 -> 6461/6965: halo-infinite's "Slate & Ash" discard removed
    # one blank-studio row; "Texas Film Commission"'s own row carried studio
    # "Certain Affinity, Inc." (it was credited via that outsource partner),
    # so its discard removed a vendor row instead.
    assert counts[""] == 6461
    assert counts["first-party"] == 0
    assert counts["independent"] == 8
    assert counts["vendor"] == 6965
    assert counts["vendor"] > 4000
