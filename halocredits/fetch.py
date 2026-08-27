import json
import re
import urllib.request
from pathlib import Path

from .config import SourceConfig

USER_AGENT = "HaloCredits/0.1 (research; local use)"

WAYPOINT_ORIGIN = "https://www.halowaypoint.com"

# The MCC credits page ships its person names only in a per-page JS chunk whose
# filename carries a build hash that changes on every Waypoint deploy
# (currently `credits-c35f203b0d507a22.js`), so the URL has to be read out of
# the served HTML rather than hardcoded.
RE_CHUNK = re.compile(r'src="(/_next/static/chunks/pages/[^"]*credits-[^"]+\.js)"')

# Separator between the frozen page HTML (which carries the i18n dictionary in
# __NEXT_DATA__) and the frozen chunk (which carries the names). Both halves are
# needed to produce a single row, so they are frozen as one artefact.
MCC_MARKER = "/*__MCC_CHUNK__*/"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        # strict, never "replace": a silent U+FFFD substitution would be written
        # out as the authoritative frozen source, and the resulting git diff would
        # look like legitimate upstream drift rather than a fetch-layer fault.
        return resp.read().decode("utf-8", errors="strict")


def fetch_html(url: str) -> str:
    return _get(url)


def extract_wikitext(payload: str) -> str:
    data = json.loads(payload)
    if "error" in data:
        raise ValueError(f"MediaWiki error: {data['error'].get('code', 'unknown')}")
    return data["parse"]["wikitext"]


def find_chunk_url(html: str) -> str:
    m = RE_CHUNK.search(html)
    if not m:
        raise ValueError("MCC credits chunk not found in page HTML")
    return WAYPOINT_ORIGIN + m.group(1)


def fetch_mcc(url: str, fetcher=None) -> str:
    """Return page HTML and its credits chunk, concatenated with a marker.

    The names live only in the JS bundle; the i18n dictionary lives only in the
    page HTML. Both are needed, so both are frozen together.
    """
    fetcher = fetcher or _get
    html = fetcher(url)
    chunk = fetcher(find_chunk_url(html))
    return html + "\n" + MCC_MARKER + "\n" + chunk


def freeze(source: SourceConfig, root: Path, fetcher=None) -> Path | None:
    """Fetch a source and write it verbatim under `root`.

    Sources with an empty url (manually supplied, e.g. IGDB) are skipped.
    """
    if not source.url:
        return None
    fetcher = fetcher or _get
    if source.parser == "waypoint_mcc":
        payload = fetch_mcc(source.url, fetcher)
    else:
        payload = fetcher(source.url)
        if source.parser == "halopedia":
            payload = extract_wikitext(payload)
    path = Path(root) / source.raw_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8", newline="\n")
    return path
