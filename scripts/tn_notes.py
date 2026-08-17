#!/usr/bin/env python3
"""
Solutions Tech Note (TN-series) drift detection for fetch-portal-docs.py.

Why this exists as its own module: the portal's *solutions* listing
(/page/documents/solutions/list) is a login-gated JS SPA, and the
/api/v1/documents/{tid}:{tid} metadata endpoint that hosted_pdf_url() and
hosted_doc_date() rely on returns 404 for this doc class. So none of the
product-doc discovery machinery works here, and TN-series notes were never
checked at all -- three of the four the wiki tracks had silently drifted.

What works instead: solutions PDFs are served publicly with no login at
https://download.nutanix.com/solutionsDocs/<slug>.pdf, and every one of
these documents stamps its version on line 1 in a fixed shape --

    v2.1 | July 2026 | TN-2156

-- in both the old pdftotext .txt sources and the newer markitdown .md
conversions. So drift detection is: fetch the PDF, read page 1, regex the
version, compare against the same regex over line 1 of the local source.
No Playwright, no login, no date manifest.

The slug is NOT derivable from the TN number and a wrong one returns 403,
not 404 (TN-2028-NC2-on-AWS -> 403, TN-2028-Nutanix-Cloud-Clusters-on-AWS
-> 200). So slugs are registered by hand in TECH_NOTES below. A
Playwright/SPA crawl of the solutions listing was considered and rejected:
it needs a logged-in session and is far more fragile than an explicit,
reviewable registry. That trade-off is deliberate.
"""

import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

SOLUTIONS_PDF_URL = "https://download.nutanix.com/solutionsDocs/{slug}.pdf"

# slug -> match patterns for the local source in wiki/01-sources/.
# Every slug here was verified to return HTTP 200. A wrong slug returns 403,
# so never guess one in -- confirm the URL resolves before adding an entry.
TECH_NOTES = {
    "TN-2156-NC2-on-Azure": ["TN-2156", "tn-2156"],
    "TN-2013-GC2-on-AWS": ["TN-2013", "tn-2013"],
    "TN-2207-NKP-Flow-Virtual-Networking": ["TN-2207", "tn-2207"],
    "TN-2028-Nutanix-Cloud-Clusters-on-AWS": ["TN-2028", "tn-2028"],
}

VERSION_RE = re.compile(r"v(\d+\.\d+)")


class TechNoteError(Exception):
    """Anything that would otherwise look like a silent false-'current'."""


def extract_version(text, source_label):
    """Pull vX.Y off the first non-empty line. Raises loudly if absent --
    never returns None, so a caller can't compare None == None and report
    'current'. This file has been bitten twice by silent-zero bugs; do not
    soften this into a return-None."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = VERSION_RE.search(line)
        if not match:
            raise TechNoteError(
                f"{source_label}: first non-empty line has no v<X.Y> "
                f"version marker: {line!r}"
            )
        return match.group(1)
    raise TechNoteError(f"{source_label}: no non-empty lines found")


def fetch_pdf_bytes(url):
    """Only HTTP 200 counts as a hit -- a 403 means the slug is wrong and
    must surface as an error, not a skipped entry."""
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            if resp.status != 200:
                raise TechNoteError(f"{url}: HTTP {resp.status}, expected 200")
            return resp.read()
    except urllib.error.HTTPError as e:
        raise TechNoteError(f"{url}: HTTP {e.code}, expected 200") from e
    except urllib.error.URLError as e:
        raise TechNoteError(f"{url}: fetch failed ({e.reason})") from e


def pdf_page1_text(pdf_bytes):
    """Page-1 text via pdftotext (poppler), which convert-source.sh's host
    already depends on. Deliberately not pypdf -- that is not installed here
    and this check does not warrant a new dependency."""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
        fh.write(pdf_bytes)
        fh.flush()
        try:
            out = subprocess.run(
                ["pdftotext", "-layout", "-f", "1", "-l", "1", fh.name, "-"],
                capture_output=True, timeout=60,
            )
        except FileNotFoundError as e:
            raise TechNoteError("pdftotext not found (install poppler-utils)") from e
        except subprocess.TimeoutExpired as e:
            raise TechNoteError("pdftotext timed out") from e
    if out.returncode != 0:
        raise TechNoteError(f"pdftotext failed: {out.stderr.decode(errors='ignore')[:200]}")
    return out.stdout.decode("utf-8", errors="ignore")


def _default_matcher(source_files, patterns):
    """Fallback so this module is testable standalone. Callers inside
    fetch-portal-docs.py pass its real source_file_matches() instead."""
    return [f for f in source_files
            if any(p.lower() in f.lower() for p in patterns)]


def find_local_source(sources_dir, source_files, patterns, matcher=None):
    """Resolve a TN's local source file. Prefers the newer .md conversion
    over the legacy .txt when both are present."""
    matcher = matcher or _default_matcher
    hits = [h for h in matcher(source_files, patterns)
            if h.lower().endswith((".md", ".txt"))]
    if not hits:
        return None
    hits.sort(key=lambda h: (not h.lower().endswith(".md"), h))
    return Path(sources_dir) / hits[0]


def check_tech_note_drift(slug, patterns, sources_dir, source_files,
                          matcher=None, fetch=fetch_pdf_bytes,
                          pdf_text=pdf_page1_text):
    """Drift status for one TECH_NOTES entry. Every failure path sets
    stale=None plus a non-None error string -- it never falls through to a
    default 'current'."""
    base = {"slug": slug, "source": None,
            "local_version": None, "portal_version": None,
            "stale": None, "error": None}

    local_path = find_local_source(sources_dir, source_files, patterns, matcher)
    if local_path is None:
        return {**base, "error": f"no local .md/.txt source matching {patterns!r}"}
    base["source"] = local_path.name

    try:
        base["local_version"] = extract_version(
            local_path.read_text(encoding="utf-8", errors="ignore"), local_path.name)
    except TechNoteError as e:
        return {**base, "error": str(e)}

    url = SOLUTIONS_PDF_URL.format(slug=slug)
    try:
        base["portal_version"] = extract_version(pdf_text(fetch(url)), url)
    except TechNoteError as e:
        return {**base, "error": str(e)}

    base["stale"] = base["local_version"] != base["portal_version"]
    return base


def check_all(sources_dir, source_files, tech_notes=None, matcher=None,
              fetch=fetch_pdf_bytes, pdf_text=pdf_page1_text):
    """Run the whole registry. Returns (stale_entries, error_entries).
    Callers must treat error_entries as loud failures, never silent passes."""
    stale_entries, error_entries = [], []
    for slug, patterns in (tech_notes or TECH_NOTES).items():
        result = check_tech_note_drift(slug, patterns, sources_dir, source_files,
                                       matcher, fetch, pdf_text)
        if result["error"] is not None:
            error_entries.append(result)
        elif result["stale"]:
            stale_entries.append(result)
    return stale_entries, error_entries
