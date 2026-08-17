#!/usr/bin/env python3
# Compares wiki tracked topics against existing source files.
# Usage: python3 check-sources.py <wiki-path>

import os
import re
import sys

wiki_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('WIKI_PATH', 'wiki')
sources_dir = os.path.join(wiki_path, '01-sources')
index_file = os.path.join(wiki_path, '00-meta', 'index.md')

if not os.path.isdir(sources_dir):
    print(f'Sources directory not found: {sources_dir}', file=sys.stderr)
    sys.exit(1)
if not os.path.isfile(index_file):
    print(f'Index file not found: {index_file}', file=sys.stderr)
    sys.exit(1)

INGESTABLE = {'.txt', '.md', '.pdf'}
source_files = sorted(
    f for f in os.listdir(sources_dir)
    if not f.startswith(('~', '.')) and os.path.splitext(f)[1].lower() in INGESTABLE
)

with open(index_file, encoding='utf-8') as fh:
    index_lines = fh.readlines()

tracked_topics = []
sections = []
for line in index_lines:
    if line.startswith('## '):
        sections.append(line[3:].strip())
    match = re.search(r'\[\[(.+?)\]\]', line)
    if match:
        tracked_topics.append(match.group(1))

print('=== WIKI SECTIONS ===')
for s in sections:
    print(' ', s)

print(f'\n=== TRACKED TOPICS ({len(tracked_topics)}) ===')
for t in tracked_topics:
    print(' ', t)

print(f'\n=== EXISTING SOURCE FILES ({len(source_files)}) ===')
for f in source_files:
    print(' ', f)

print('\n=== SUMMARY ===')
print(f'Sections in index: {len(sections)}')
print(f'Topics tracked:    {len(tracked_topics)}')
print(f'Source files:      {len(source_files)}')
print('\nPass this output to Claude alongside the portal doc list to identify gaps.')
