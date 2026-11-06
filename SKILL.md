---
name: wiki-doc-sync
description: Checks the Nutanix portal for updates to documents already sourced in an Obsidian wiki vault, then ingests new versions. Uses Playwright with login. Only checks products that already have source files in wiki/01-sources/ — does not discover new products. Use when asked to sync the wiki, check for new Nutanix docs, find missing documentation, or refresh wiki sources.
---

# Wiki Doc Sync

Checks for updated versions of docs already in the wiki. Only covers products already sourced in `wiki/01-sources/`. Login required.

The wiki is an **Obsidian vault** — pages use `[[wikilinks]]`, and `00-meta/index.md` is the link hub the gap check reads. Point the scripts at your vault with the `WIKI_PATH` environment variable (or `--wiki` / a positional arg); it defaults to `./wiki` relative to the current directory.

```bash
export WIKI_PATH=~/path/to/your-vault/wiki
```

Expected vault layout:

```
wiki/
  00-meta/index.md      # wikilink hub — tracked topics
  01-sources/           # raw source docs (PDF/MD/TXT) + converted .md
```

## First-time setup — save your session

```bash
python3 scripts/fetch-portal-docs.py \
    --visible --save-cookies ~/.config/nutanix-cookies.json
```
Opens a browser. Log in to the portal, then press Enter. Cookies are saved for future runs.

Chromium is found automatically under `~/.cache/ms-playwright/`; override with `PLAYWRIGHT_CHROME=/path/to/chrome`.

## Workflow

### 1. Inventory existing sources
```bash
python3 scripts/check-sources.py "$WIKI_PATH"
```

### 2. Check portal for gaps and updates
```bash
# Using saved session (fastest)
python3 scripts/fetch-portal-docs.py \
    --cookies-file ~/.config/nutanix-cookies.json

# With credentials
python3 scripts/fetch-portal-docs.py \
    --email you@example.com --password yourpass
```
Outputs a JSON report: for each tracked product, what docs the portal lists vs what's in the wiki. Flags gaps.

### 3. Download flagged docs (optional — adds --download flag)
```bash
python3 scripts/fetch-portal-docs.py \
    --cookies-file ~/.config/nutanix-cookies.json --download
```
Downloads PDFs for flagged docs directly to `wiki/01-sources/`. Hosted docs (no PDF link on the page) are now also downloaded automatically from `https://download.nutanix.com/documentation/hosted/<targetId>.pdf` (public, no login) and saved as `<targetId>.pdf`. Only if that URL doesn't return a PDF does the doc get a note to copy text manually.

### 4. Convert each new file to Markdown
```bash
scripts/convert-source.sh \
    "$WIKI_PATH/01-sources/<file>.pdf"   # writes <file>.md beside it
```
Uses markitdown — preserves headings and tables that `pdftotext` drops, and handles PDF/PPTX/DOCX/XLSX/HTML/VTT with one tool. Read the `.md` (not the raw file) when ingesting. Note: image-only PDFs/decks and diagram PNGs yield little text — transcribe those manually.

### 5. Ingest each new file
```
INGEST <filename>
```
Read your vault's ingest conventions (e.g. `wiki/CLAUDE.md` and `wiki/00-meta/schema.md`) before each ingest. Log to `changelog.md`, update `index.md`.

## Tracked products
The script covers 18 portal products already in the wiki: Data Lens, Cloud Clusters (NC2), GC2, Flow Virtual Networking, Flow standalone, Nutanix Disaster Recovery, Files, NKP, Prism, NCM (Next-Gen), Cost Governance, Intelligent Operations, AOS Security, Enterprise AI, NDB, Nutanix Central, Foundation, LCM.

To add a new product: edit `PRODUCT_MAP` in `fetch-portal-docs.py` and add the portal `filterVal` name alongside keyword patterns matching its existing source files.

## Notes
- Docs marked "Hosted" on the portal are live HTML with no versioned PDF in the listing, but the full PDF is published at `https://download.nutanix.com/documentation/hosted/<targetId>.pdf` (public, no login). `--download` fetches these automatically. The portal page body itself is login-gated; the download host is not.
