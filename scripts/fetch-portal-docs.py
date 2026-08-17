#!/usr/bin/env python3
"""
Checks the Nutanix portal for updates to documents already sourced in the wiki.
Only looks at products that already have source files in wiki/01-sources/.
Requires login to access document detail pages and downloads.

Usage:
    # First time: save session cookies via visible browser login
    python3 fetch-portal-docs.py --visible --save-cookies ~/.config/nutanix-cookies.json

    # Subsequent runs: reuse saved session
    python3 fetch-portal-docs.py --cookies-file ~/.config/nutanix-cookies.json

    # With credentials
    python3 fetch-portal-docs.py --email you@example.com --password yourpass

    # Download flagged files to wiki/01-sources/
    python3 fetch-portal-docs.py --cookies-file ~/.config/nutanix-cookies.json --download

Output: JSON report to stdout (stderr for status messages)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

CHROME = os.environ.get('PLAYWRIGHT_CHROME') or next(
    (str(p) for p in sorted(
        Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'),
        reverse=True)),
    'chromium')
from tn_notes import SOLUTIONS_PDF_URL, check_all as check_tech_notes

PORTAL_BASE = 'https://portal.nutanix.com'
DOCS_BASE = f'{PORTAL_BASE}/page/documents/list?type=software'
WIKI_SOURCES = Path(os.environ.get('WIKI_PATH', 'wiki')) / '01-sources'
LAUNCH_ARGS = ['--no-sandbox', '--disable-dev-shm-usage', '--disable-crash-reporter']

# Maps portal filterVal to source file keyword patterns already in the wiki.
# Only products with existing source files are listed here.
PRODUCT_MAP = {
    'Cloud Clusters (NC2)': ['nc2-aws', 'nc2-azure', 'nc2-gcp', 'tn-2028', 'tn-2156', 'nc2-7.', '7.6---whats-new'],
    'Government Cloud Clusters (GC2)': ['gc2', 'gov-cloud', 'tn-2013', 'Government-Cloud-Clusters'],
    'Flow Virtual Networking': ['flow-vn'],
    'Flow (Standalone Mode)': ['flow-cni', 'Flow-Virtual-Networking-Guide-Flow-Controller',
                               'Flow-Management-Guide', 'Flow-Network-Security-Guide'],
    'Nutanix Disaster Recovery': ['dr-draas', 'Disaster-Recovery'],
    'Files': ['files-guide', 'files-manager'],
    'Nutanix Kubernetes Platform': ['nkp-guide', 'TN-2207', 'NKP'],
    'Prism': ['prism-central'],
    'Nutanix Cloud Manager (Next-Gen)': ['ncm-guide'],
    'Cost Governance': ['ncm-guide'],
    'Intelligent Operations': ['ncm-guide', 'Intelligent-Operations'],
    # 'security-guide.txt' (exact) + 'Nutanix-Security-Guide'; NOT bare
    # 'security-guide', which collides with the Flow *Network-Security-Guide*.
    'AOS Security': ['security-guide.txt', 'Nutanix-Security-Guide'],
    'Nutanix Enterprise AI': ['enterprise-ai', 'Enterprise-AI'],
    'Nutanix Database Service': ['NDB'],
    'Nutanix Central': ['Nutanix-Central'],
    'Foundation': ['foundation-install', 'Field-Installation-Guide'],
    'LCM': ['lcm-guide', 'Life-Cycle-Manager'],
}


def launch_browser(playwright, headless=True):
    return playwright.chromium.launch(
        executable_path=CHROME,
        headless=headless,
        args=LAUNCH_ARGS,
    )


def is_authenticated(page):
    for _ in range(10):
        body = page.inner_text('body')
        if 'viewing the Support and Insights portal as a guest' not in body:
            return True
        time.sleep(1)
    return False


def login(page, email, password):
    print('Logging in...', file=sys.stderr)
    try:
        page.wait_for_selector('input[type=email], input[name=email], #username', timeout=15000)
        page.fill('input[type=email], input[name=email], #username', email)
        time.sleep(0.3)
        page.wait_for_selector('input[type=password]', timeout=10000)
        page.fill('input[type=password]', password)
        page.keyboard.press('Enter')
        page.wait_for_url(lambda u: 'portal.nutanix.com' in u and 'login' not in u.lower(), timeout=30000)
        print('Login successful.', file=sys.stderr)
    except Exception as e:
        print(f'Login failed: {e}', file=sys.stderr)
        sys.exit(1)


def wait_for_manual_login(page):
    print('Browser is open. Log in to the portal. Waiting up to 3 minutes...', file=sys.stderr)
    for i in range(180):
        time.sleep(1)
        if is_authenticated(page):
            print('Login detected.', file=sys.stderr)
            return
        if i % 15 == 0 and i > 0:
            print(f'Still waiting for login... ({i}s elapsed)', file=sys.stderr)
    print('Timed out waiting for login.', file=sys.stderr)
    sys.exit(1)


def get_docs_for_product(page, product_name):
    """Navigate to a product's doc list and return available docs."""
    import urllib.parse
    url = f"{DOCS_BASE}&filterKey=software&filterVal={urllib.parse.quote(product_name)}"

    for attempt in range(3):
        try:
            page.goto(url)
            page.wait_for_load_state('networkidle', timeout=20000)
            time.sleep(2)

            docs = page.evaluate('''() => {
                const rows = [];
                document.querySelectorAll('tr, [role=row]').forEach(row => {
                    const link = row.querySelector('a[href*="documents/details"]');
                    if (!link) return;
                    const cells = row.querySelectorAll('td, [role=cell]');
                    const cellTexts = Array.from(cells).map(c => c.textContent.trim());
                    rows.push({
                        title: link.textContent.trim(),
                        href: link.getAttribute('href'),
                        version: cellTexts[2] || null,
                        category: cellTexts[3] || null,
                    });
                });
                return rows;
            }''')
            return docs
        except Exception as e:
            if attempt < 2:
                print(f'  Retrying {product_name} (attempt {attempt + 2})...', file=sys.stderr)
                time.sleep(3)
            else:
                print(f'  Failed to fetch {product_name}: {e}', file=sys.stderr)
                return []


def version_token(version):
    """Normalized numeric version token from a portal version string, or None.
    'pc.7.6'->'7.6', 'Controller 7.6'->'7.6', 'pc.2024.2'->'2024.2',
    '5.11.x'->'5.11', '2.10'->'2.10', 'Hosted'->None."""
    if not version:
        return None
    m = re.search(r'\d+(?:\.\d+)+', version)
    return m.group(0) if m else None


def source_has_version(sources_dir, matched_sources, token):
    """True if the version token appears in a matched source's filename or,
    for text sources, its content. Boundary-aware: the token must not be flanked
    by digits/dots/underscores, so a bare '7.6' does NOT match inside an IP like
    '10.47.6.141' or a version like '6.7.6' (that collision was a real
    false-negative that masked the AOS Security 7.6 refresh)."""
    # Wiki PDF filenames use underscores for dots (e.g. v2_10 / vpc_7_6).
    # Reject only a flanking DIGIT, so '7.6' misses IPs ('10.47.6.141' -> the
    # '7.6' is preceded by '4') and '7.65', but still matches 'pc.2024.2'
    # (token '2024.2' is preceded by a dot, which is allowed) and 'vpc_7_6.pdf'.
    dotted = re.escape(token)
    under = re.escape(token.replace('.', '_'))
    pat = re.compile(rf'(?<!\d){dotted}(?!\d)' + '|' + rf'(?<!\d){under}(?!\d)')
    for sf in matched_sources:
        if pat.search(sf):
            return True
        p = sources_dir / sf
        if p.suffix.lower() in ('.txt', '.md'):
            try:
                if pat.search(p.read_text(errors='ignore')):
                    return True
            except OSError:
                pass
    return False


def source_file_matches(source_files, patterns):
    """Check which source files match any of the given patterns."""
    matched = []
    for f in source_files:
        if any(p.lower() in f.lower() for p in patterns):
            matched.append(f)
    return matched


def hosted_target_id(detail_href):
    """Extract the doc targetId from a detail href.
    '/page/documents/details?targetId=Foo:Foo' -> 'Foo'."""
    import urllib.parse
    q = urllib.parse.urlparse(detail_href).query
    target = urllib.parse.parse_qs(q).get('targetId', [''])[0]
    return target.split(':')[0] if target else ''


_META_CACHE = {}


def doc_metadata(detail_href):
    """Portal document metadata (public JSON API, no login). Cached per run.
    Carries rootPdfUrl, DC_Date/documentDate, version, toc, etc."""
    tid = hosted_target_id(detail_href)
    if not tid:
        return {}
    if tid in _META_CACHE:
        return _META_CACHE[tid]
    meta = {}
    try:
        meta_url = f'{PORTAL_BASE}/api/v1/documents/{tid}:{tid}'
        with urllib.request.urlopen(meta_url, timeout=20) as resp:
            meta = json.loads(resp.read().decode('utf-8', errors='ignore'))
    except Exception:
        meta = {}
    _META_CACHE[tid] = meta
    return meta


def hosted_pdf_url(detail_href):
    """Public full-guide PDF URL for a doc, from metadata `rootPdfUrl`. This is
    authoritative — the PDF path varies by product (/documentation/vpc76/,
    /Foundation/, /hosted/, ...), so the old hardcoded /hosted/ guess 404/403'd."""
    return doc_metadata(detail_href).get('rootPdfUrl') or None


def hosted_doc_date(detail_href):
    """ISO publish date of a doc from metadata (DC_Date, fallback documentDate).
    Used for drift detection on 'Hosted' rolling docs that carry no version."""
    m = doc_metadata(detail_href)
    return m.get('DC_Date') or m.get('documentDate') or None


HOSTED_MANIFEST_NAME = '.hosted-doc-dates.json'


def load_hosted_dates(sources_dir):
    """targetId -> last-ingested DC_Date, from the manifest in sources_dir."""
    p = sources_dir / HOSTED_MANIFEST_NAME
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_hosted_date(sources_dir, tid, date):
    """Record the DC_Date we just ingested for a hosted doc."""
    if not tid or not date:
        return
    p = sources_dir / HOSTED_MANIFEST_NAME
    data = load_hosted_dates(sources_dir)
    data[tid] = date
    try:
        p.write_text(json.dumps(data, indent=1, sort_keys=True))
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--email', help='Nutanix portal email')
    parser.add_argument('--password', help='Nutanix portal password')
    parser.add_argument('--cookies-file', help='Path to saved session cookies JSON')
    parser.add_argument('--save-cookies', help='Save session cookies to this file after login')
    parser.add_argument('--visible', action='store_true', help='Open visible browser for manual login')
    parser.add_argument('--download', action='store_true', help='Download flagged docs to wiki/01-sources/')
    parser.add_argument('--wiki', default=str(WIKI_SOURCES), help='Path to wiki/01-sources/ directory')
    args = parser.parse_args()

    sources_dir = Path(args.wiki)
    source_files = [f.name for f in sources_dir.iterdir()
                    if f.suffix.lower() in ('.txt', '.pdf', '.md') and not f.name.startswith(('~', '.'))]

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = launch_browser(p, headless=not args.visible)

        # Restore full session state (cookies + localStorage) if available
        storage_file = args.cookies_file
        if storage_file and os.path.exists(storage_file):
            context = browser.new_context(storage_state=storage_file)
            print(f'Loaded session state from {storage_file}', file=sys.stderr)
        else:
            context = browser.new_context()

        page = context.new_page()
        page.goto(DOCS_BASE)
        page.wait_for_load_state('networkidle', timeout=20000)

        # Attempt login if credentials/visible flag provided; otherwise proceed as guest
        if not is_authenticated(page):
            if args.visible:
                wait_for_manual_login(page)
            elif args.email and args.password:
                login(page, args.email, args.password)
            else:
                print('Running as guest (doc listings are publicly accessible).', file=sys.stderr)

        if args.save_cookies:
            context.storage_state(path=args.save_cookies)
            print(f'Saved full session state to {args.save_cookies}', file=sys.stderr)

        report = {'products': []}

        for product, patterns in PRODUCT_MAP.items():
            print(f'Checking: {product}', file=sys.stderr)
            portal_docs = get_docs_for_product(page, product)
            matched_sources = source_file_matches(source_files, patterns)

            product_report = {
                'product': product,
                'portal_docs': portal_docs,
                'wiki_sources': matched_sources,
                'gaps': [],
                'stale': [],
            }

            # Flag portal docs with no obvious match in wiki sources (missing),
            # matched docs whose portal version isn't in the source we hold, and
            # 'Hosted' rolling docs (no version) whose portal date is newer than
            # the date we last ingested.
            hosted_dates = load_hosted_dates(sources_dir)
            for doc in portal_docs:
                # 'Documentation Library' entries are 2-topic stub landing pages,
                # not real guides — they perpetually false-flag. Skip them.
                if 'documentation library' in doc['title'].lower():
                    continue
                title_words = set(doc['title'].lower().split())
                has_match = any(
                    any(w in sf.lower() for w in title_words if len(w) > 4)
                    for sf in matched_sources
                )
                if not has_match:
                    product_report['gaps'].append(doc)
                    continue
                token = version_token(doc.get('version'))
                if token:
                    if not source_has_version(sources_dir, matched_sources, token):
                        doc['wiki_version_missing'] = token
                        product_report['stale'].append(doc)
                else:
                    # Hosted / unversioned rolling doc: compare publish dates.
                    portal_date = hosted_doc_date(doc['href'])
                    known = hosted_dates.get(hosted_target_id(doc['href']))
                    if portal_date and (known is None or portal_date > known):
                        doc['hosted_portal_date'] = portal_date
                        doc['hosted_known_date'] = known
                        product_report['stale'].append(doc)

            report['products'].append(product_report)

            # Download flagged docs if requested (missing + stale/newer-version)
            to_download = product_report['gaps'] + product_report['stale']
            if args.download and to_download:
                for doc in to_download:
                    # Authoritative full-guide PDF from doc metadata (rootPdfUrl).
                    # Public, no login, correct per-product path. Named by targetId
                    # so its version token lets future syncs match it.
                    hurl = hosted_pdf_url(doc['href'])
                    if hurl:
                        dest = sources_dir / (hosted_target_id(doc['href']) + '.pdf')
                        print(f'Downloading (rootPdfUrl): {doc["title"]}', file=sys.stderr)
                        try:
                            urllib.request.urlretrieve(hurl, dest)
                            with open(dest, 'rb') as fh:
                                is_pdf = fh.read(4) == b'%PDF'
                            if is_pdf and dest.stat().st_size > 1000:
                                doc['downloaded_to'] = str(dest)
                                doc['download_via'] = 'rootPdfUrl'
                                # Record publish date so future syncs can detect
                                # a newer refresh of this (often Hosted) doc.
                                save_hosted_date(sources_dir, hosted_target_id(doc['href']),
                                                 hosted_doc_date(doc['href']))
                                print(f'  saved {dest} ({dest.stat().st_size} bytes)', file=sys.stderr)
                            else:
                                dest.unlink(missing_ok=True)
                                doc['download_note'] = f'{hurl} returned non-PDF. Copy text manually.'
                        except Exception as e:
                            doc['download_note'] = f'{hurl} failed ({e}). Copy text manually.'
                    else:
                        doc['download_note'] = 'No rootPdfUrl in metadata. Copy text manually.'

        browser.close()

    # Solutions Tech Notes (TN-series) are not in the software-docs listing at
    # all, so the product loop above can never see them. They get their own
    # pass: public PDF fetch + line-1 version compare. See tn_notes.py.
    tn_stale, tn_errors = check_tech_notes(sources_dir, source_files,
                                           matcher=source_file_matches)
    report['tech_notes'] = {'stale': tn_stale, 'errors': tn_errors}
    for err in tn_errors:
        print(f'ERROR: tech note {err["slug"]}: {err["error"]}', file=sys.stderr)

    if args.download and tn_stale:
        for entry in tn_stale:
            url = SOLUTIONS_PDF_URL.format(slug=entry['slug'])
            dest = sources_dir / (entry['slug'] + '.pdf')
            print(f'Downloading (solutionsDocs): {entry["slug"]} '
                  f'{entry["local_version"]} -> {entry["portal_version"]}', file=sys.stderr)
            try:
                urllib.request.urlretrieve(url, dest)
                with open(dest, 'rb') as fh:
                    is_pdf = fh.read(4) == b'%PDF'
                if is_pdf and dest.stat().st_size > 1000:
                    entry['downloaded_to'] = str(dest)
                    print(f'  saved {dest} ({dest.stat().st_size} bytes)', file=sys.stderr)
                else:
                    dest.unlink(missing_ok=True)
                    entry['download_note'] = f'{url} returned non-PDF. Copy text manually.'
            except Exception as e:
                entry['download_note'] = f'{url} failed ({e}). Copy text manually.'

    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
