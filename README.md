# Halo Credits

Every person credited across 25 years of Halo, from Combat Evolved to Campaign Evolved. 9,174 names, parsed from published credit rolls into an interactive career grid and a print poster.

**[View the live page](https://hiiammoot.github.io/HaloCredits/)**

The full-resolution poster PNG and PDF are too large for a git repo, so they live in [Releases](https://github.com/HiIAmMoot/HaloCredits/releases) instead.

## What this is

Twelve mainline campaign releases, run through the same measurement: parsed into one row per credit, matched into people by name, laid out by which games they appear on. The page shows every person as a row, their credited games as a chip on that row, and connects consecutive games with a line so a career reads as a shape rather than a list. Roles, studios, publisher staff, community volunteers and reprinted rosters all get their own colour, explained in the key above the grid and in the notes below it.

Halo Wars, Halo Wars 2, Spartan Assault, Spartan Strike and Fireteam Raven are out of scope. This covers the twelve campaign releases only.

## How it was built

Four sources feed it: Halopedia, Halo Waypoint, IGDB and MobyGames. Nothing is sampled and nothing is estimated. If a name is on the sheet, a credit roll printed it.

A credit roll is not a staff list, though, and that's the real limit here. It records who a studio chose to print, not who did the work. People leave before a game ships and lose their credit, contractors appear under an agency rather than their own name, and whole disciplines are sometimes collapsed into a single line. Where the credits are silent, so is this.

Matching people across twenty-five years is done by name, so two different people who share one are counted as one, and one person credited under two spellings is counted as two. Hundreds of those have been resolved by hand; the ones that survive are the ones nobody has spotted yet.

The same rules run over all twelve releases, so a comparison between two games compares the same measurement, and a handful of exact counts are pinned in the test suite, so a change that quietly moves a number fails the build instead of shipping unnoticed.

Built in Python with Claude Code. The sheet is drawn as SVG and rendered to image with Playwright's headless Chromium, and NumPy and Pillow do the pixel work behind the cover art and the logos.

## Repo layout

```
halocredits/   the parsing, identity-matching and role-classification package
tools/         the page and poster generators (build_grid_page.py, export_poster.py, ...)
config/        name fixes, aliases, role rules, the written copy on the page
data/          the parsed credits, one CSV per game, plus the resolved people table
tests/         pins exact counts against the committed data
art/           every image asset, downsized and converted to WebP
  art/cover/         cover art for the poster's background wash
  art/logos/         game and studio wordmarks
  art/beam-tower/    the poster's beam tower concept art
index.html     the page this repo publishes, prebuilt and self-contained
```

`raw/`, the scraped Halopedia/Waypoint/MobyGames/IGDB source pages the parser reads, is not included: it's third-party content this repo doesn't have the right to redistribute. Everything downstream of it is, so the page and poster regenerate fine from what's here; a from-scratch re-scrape does not.

## Running it

```
pip install -r requirements.txt
playwright install chromium
```

Regenerate the page:

```
python tools/build_grid_page.py index.html
```

Regenerate the poster (verified working from a clean checkout of this repo, full resolution, PNG and PDF both):

```
python tools/export_poster.py --pdf
```

Check the pinned counts:

```
pytest
```

## Credits

Official cover art, promotional art, game logos and studio logos courtesy of Bungie, Xbox Game Studios, 343 Industries, Halo Studios and the various artists who made them. Beam tower concept art by Ben Mauro.

Built by [@HiIAmMoot](https://x.com/HiIAmMoot) ([GitHub](https://github.com/HiIAmMoot)).

## License

MIT. See [LICENSE](LICENSE).
