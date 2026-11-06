# wiki-doc-sync

A [Claude Code](https://claude.com/claude-code) skill that keeps an **Obsidian wiki vault** in sync with the [Nutanix support portal](https://portal.nutanix.com).

It checks the portal for newer versions of documents you have already sourced, flags version drift and gaps, and downloads the new PDFs into your vault's `01-sources/` folder ready for ingest.

It does **not** discover new products. It only tracks what your vault already covers.

Data Lens is supported when your vault already contains source files matching `Data-Lens`.

## Install

Requires Python 3.10–3.14. [MarkItDown](https://github.com/microsoft/markitdown) is required to convert source documents to Markdown; Playwright and Chromium handle portal access.

```bash
python3 --version
git clone https://github.com/lessnercode/wiki-doc-sync ~/.claude/skills/wiki-doc-sync
pip install playwright && playwright install chromium
python3 -m pip install --target "$HOME/.local/markitdown-lib" 'markitdown[all]'
export WIKI_PATH=~/path/to/your-vault/wiki
```

The MarkItDown install command includes its optional format dependencies and installs into the default `MARKITDOWN_LIB` directory used by `convert-source.sh`.

Verify the MarkItDown installation:

```bash
PYTHONPATH="${MARKITDOWN_LIB:-$HOME/.local/markitdown-lib}" python3 -m markitdown --help
```

## Vault layout

The wiki is an Obsidian vault. `00-meta/index.md` is the wikilink hub the gap check reads, and raw source documents live in `01-sources/`:

```
wiki/
  00-meta/index.md      # [[wikilinks]] to tracked topics
  01-sources/           # source PDFs + their converted .md
```

## Use

```bash
# one-time: log in and save the session
python3 scripts/fetch-portal-docs.py --visible --save-cookies ~/.config/nutanix-cookies.json

# what's in the vault now
python3 scripts/check-sources.py "$WIKI_PATH"

# what the portal has that the vault doesn't
python3 scripts/fetch-portal-docs.py --cookies-file ~/.config/nutanix-cookies.json

# fetch the flagged docs
python3 scripts/fetch-portal-docs.py --cookies-file ~/.config/nutanix-cookies.json --download

# convert a downloaded doc to Markdown for ingest
scripts/convert-source.sh "$WIKI_PATH/01-sources/<file>.pdf"
```

Conversion writes `<file>.md` beside the original document. To choose a different output path, pass it as the second argument:

```bash
scripts/convert-source.sh "$WIKI_PATH/01-sources/<file>.pdf" \
  "/path/to/output.md"
```

Full workflow, including the ingest step, is in [SKILL.md](SKILL.md).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `WIKI_PATH` | `./wiki` | Path to the Obsidian vault's wiki root |
| `PLAYWRIGHT_CHROME` | auto-detected under `~/.cache/ms-playwright/` | Chromium binary |
| `MARKITDOWN_LIB` | `~/.local/markitdown-lib` | markitdown install used by `convert-source.sh` |

Portal credentials are never stored in this repo. They are passed at runtime via `--email`/`--password`, or read from a session cookie file you save yourself.

## Tests

```bash
cd scripts && python3 test_version_drift.py && python3 test_tn_notes.py
```
