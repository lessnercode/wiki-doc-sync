#!/usr/bin/env bash
# Convert a source document (PDF, PPTX, DOCX, XLSX, HTML, VTT...) to Markdown
# for wiki ingest, using markitdown. Output preserves headings and tables that
# pdftotext drops.
#
# Usage:
#   convert-source.sh <input-file> [output.md]
# If output is omitted, writes alongside the input with a .md extension.

set -euo pipefail

MARKITDOWN_LIB="${MARKITDOWN_LIB:-$HOME/.local/markitdown-lib}"

if [ $# -lt 1 ]; then
    echo "usage: convert-source.sh <input-file> [output.md]" >&2
    exit 2
fi

in="$1"
out="${2:-${in%.*}.md}"

if [ ! -e "$in" ]; then
    echo "error: input not found: $in" >&2
    exit 1
fi

PYTHONPATH="$MARKITDOWN_LIB" python3 -m markitdown "$in" -o "$out"
echo "wrote: $out ($(wc -l <"$out") lines)"
