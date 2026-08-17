#!/usr/bin/env python3
"""Offline self-check for tn_notes.py. No network: the fetcher and the PDF
text extractor are injected. Run: python3 test_tn_notes.py"""

import sys
import tempfile
from pathlib import Path

from tn_notes import (TechNoteError, check_all, check_tech_note_drift,
                      extract_version, find_local_source)

PASS = FAIL = 0


def check(label, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  ok   {label}')
    else:
        FAIL += 1
        print(f'  FAIL {label}')


def expect_raises(label, fn):
    try:
        fn()
    except TechNoteError:
        check(label, True)
    else:
        check(label, False)


def main():
    print('extract_version')
    check('TN-2156 header',
          extract_version('v2.1 | July 2026 | TN-2156\nSOLUTIONS DOCUMENT', 'x') == '2.1')
    check('legacy txt header',
          extract_version('v1.9 | August 2025 | TN-2156', 'x') == '1.9')
    check('two-digit minor',
          extract_version('v2.10 | May 2026 | TN-2028', 'x') == '2.10')
    check('leading blank lines skipped',
          extract_version('\n\n  v1.2 | July 2026 | TN-2013\n', 'x') == '1.2')
    expect_raises('no version marker raises',
                  lambda: extract_version('SOLUTIONS DOCUMENT\nv1.0 later', 'x'))
    expect_raises('empty text raises', lambda: extract_version('   \n\n', 'x'))

    print('find_local_source')
    with tempfile.TemporaryDirectory() as d:
        files = ['TN-2156-NC2-on-Azure.md', 'tn-2156-nc2-azure.txt', 'unrelated.pdf']
        got = find_local_source(d, files, ['TN-2156', 'tn-2156'])
        check('prefers .md over legacy .txt', got.name == 'TN-2156-NC2-on-Azure.md')
        check('no match returns None',
              find_local_source(d, files, ['TN-9999']) is None)
        check('ignores .pdf-only matches',
              find_local_source(d, ['TN-1234.pdf'], ['TN-1234']) is None)

    print('check_tech_note_drift')
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'TN-2156-NC2-on-Azure.md').write_text('v1.9 | August 2025 | TN-2156\n')
        files = ['TN-2156-NC2-on-Azure.md']
        fake_fetch = lambda url: b'%PDF-fake'

        r = check_tech_note_drift('TN-2156-NC2-on-Azure', ['TN-2156'], d, files,
                                  fetch=fake_fetch,
                                  pdf_text=lambda b: 'v2.1 | July 2026 | TN-2156')
        check('v1.9 vs v2.1 -> stale', r['stale'] is True and r['error'] is None)
        check('reports both versions',
              r['local_version'] == '1.9' and r['portal_version'] == '2.1')

        r = check_tech_note_drift('TN-2156-NC2-on-Azure', ['TN-2156'], d, files,
                                  fetch=fake_fetch,
                                  pdf_text=lambda b: 'v1.9 | August 2025 | TN-2156')
        check('same version -> current', r['stale'] is False and r['error'] is None)

        def boom(url):
            raise TechNoteError(f'{url}: HTTP 403, expected 200')

        r = check_tech_note_drift('TN-2028-WRONG-SLUG', ['TN-2156'], d, files,
                                  fetch=boom, pdf_text=lambda b: '')
        check('403 -> stale=None + error', r['stale'] is None and '403' in r['error'])

        r = check_tech_note_drift('TN-2156-NC2-on-Azure', ['TN-2156'], d, files,
                                  fetch=fake_fetch, pdf_text=lambda b: 'no version here')
        check('unparseable PDF -> stale=None + error',
              r['stale'] is None and r['error'] is not None)

        r = check_tech_note_drift('TN-9999-Nope', ['TN-9999'], d, files,
                                  fetch=fake_fetch, pdf_text=lambda b: 'v1.0 | x')
        check('missing local source -> stale=None + error',
              r['stale'] is None and 'no local' in r['error'])

    print('check_all')
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'TN-2156-NC2-on-Azure.md').write_text('v1.9 | August 2025 | TN-2156\n')
        Path(d, 'TN-2207-NKP-Flow-Virtual-Networking.md').write_text('v2.0 | May 2026 | TN-2207\n')
        files = ['TN-2156-NC2-on-Azure.md', 'TN-2207-NKP-Flow-Virtual-Networking.md']
        versions = {'TN-2156-NC2-on-Azure': 'v2.1 | July 2026 | TN-2156',
                    'TN-2207-NKP-Flow-Virtual-Networking': 'v2.0 | May 2026 | TN-2207',
                    'TN-9999-Missing': 'v1.0 | May 2026 | TN-9999'}
        registry = {k: [k.split('-N')[0] if False else k[:7]] for k in versions}
        stale, errors = check_all(
            d, files, tech_notes=registry,
            fetch=lambda url: url.rsplit('/', 1)[-1][:-4].encode(),
            pdf_text=lambda b: versions[b.decode()])
        check('one stale (TN-2156)',
              len(stale) == 1 and stale[0]['slug'] == 'TN-2156-NC2-on-Azure')
        check('one error (TN-9999, no local source)',
              len(errors) == 1 and errors[0]['slug'] == 'TN-9999-Missing')
        check('current doc is neither stale nor error',
              all(e['slug'] != 'TN-2207-NKP-Flow-Virtual-Networking'
                  for e in stale + errors))

    print(f'\n{PASS} passed, {FAIL} failed')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
