#!/usr/bin/env bash
# Render docs/presentation.md into the animated docs/presentation.gif shown in the README.
#
# Usage:   docs/render-gif.sh [output.gif]        (default: docs/presentation.gif)
# Tunable: WIDTH=1200 COLS=100 ROWS=32 CHROME=/path/to/chrome docs/render-gif.sh
#
# Needs presenterm, Google Chrome, pdftoppm (poppler), ffmpeg, ImageMagick 7 (magick) and
# python3. No weasyprint: presenterm exports HTML, headless Chrome prints it to PDF.
# Route: presenterm HTML export -> one printed page per slide -> PNG frames -> GIF with one
# shared palette (keeps the code-block background apart from the page background), 3 s on
# the first and last slide, 4 s on the rest, looping. Everything happens in a temporary
# directory that is removed on exit; Chrome runs with a throwaway profile and its background
# network features off.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deck="$here/presentation.md"
out="${1:-$here/presentation.gif}"
WIDTH="${WIDTH:-1200}"
COLS="${COLS:-100}"
ROWS="${ROWS:-32}"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

for tool in presenterm pdftoppm ffmpeg magick python3; do
    command -v "$tool" >/dev/null || { echo "render-gif: $tool not found" >&2; exit 1; }
done
[ -x "$CHROME" ] || { echo "render-gif: Chrome not found at $CHROME (set CHROME=...)" >&2; exit 1; }
case "$out" in /*) ;; *) out="$PWD/$out" ;; esac

tmp="$(mktemp -d "${TMPDIR:-/tmp}/render-gif.XXXXXX")"
chrome_pid=""
cleanup() {
    if [ -n "$chrome_pid" ]; then kill "$chrome_pid" 2>/dev/null || true; fi
    pkill -f "user-data-dir=$tmp/chrome" 2>/dev/null || true   # its helper processes
    rm -rf "$tmp"
}
trap cleanup EXIT

# 1. presenterm exports HTML at a fixed terminal size
printf 'export:\n  dimensions:\n    columns: %s\n    rows: %s\n' "$COLS" "$ROWS" > "$tmp/config.yaml"
presenterm -c "$tmp/config.yaml" --export-html -o "$tmp/deck.html" "$deck" < /dev/null > "$tmp/export.log" 2>&1 \
    || { cat "$tmp/export.log" >&2; exit 1; }

# 2. the export shows one slide at a time with a script: drop it, print one page per slide
python3 - "$tmp/deck.html" "$tmp/print.html" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
s = open(src, encoding="utf-8").read()
s = re.sub(r"<script>.*?</script>", "", s, flags=re.S)
m = re.search(r"height: (\d+)px;\s*transform-origin", s)
if not m:
    sys.exit("render-gif: unexpected presenterm HTML (no page height found)")
css = """
        pre { font-family: Menlo, "SF Mono", monospace; }
        body { height: auto !important; }
        .container { height: %spx; overflow: hidden; break-after: page; page-break-after: always; }
""" % m.group(1)
open(dst, "w", encoding="utf-8").write(s.replace("</style>", css + "</style>", 1))
PY

# 3. headless Chrome prints the PDF, then lingers: wait for the write, then stop it
"$CHROME" --headless=new --disable-gpu --no-first-run --no-default-browser-check \
    --user-data-dir="$tmp/chrome" --disable-background-networking --disable-component-update \
    --disable-sync --disable-extensions --disable-default-apps --disable-domain-reliability \
    --disable-features=Translate,OptimizationHints,MediaRouter,AutofillServerCommunication \
    --no-pdf-header-footer --print-to-pdf="$tmp/deck.pdf" "file://$tmp/print.html" > "$tmp/chrome.log" 2>&1 &
chrome_pid=$!
for _ in $(seq 1 90); do
    grep -q 'bytes written' "$tmp/chrome.log" 2>/dev/null && break
    sleep 1
done
grep -q 'bytes written' "$tmp/chrome.log" || { echo "render-gif: Chrome did not write the PDF" >&2; tail -5 "$tmp/chrome.log" >&2; exit 1; }
sleep 1
kill "$chrome_pid" 2>/dev/null || true
pkill -f "user-data-dir=$tmp/chrome" 2>/dev/null || true
chrome_pid=""

# 4. one PNG per slide
mkdir "$tmp/frames"
pdftoppm -png -scale-to-x "$WIDTH" -scale-to-y -1 "$tmp/deck.pdf" "$tmp/frames/s"
frames=("$tmp"/frames/s-*.png)
n=${#frames[@]}
[ "$n" -ge 2 ] || { echo "render-gif: expected several slides, got $n" >&2; exit 1; }

# 5. per-slide durations (concat repeats the last file so its duration is honoured)
: > "$tmp/list.txt"
for i in "${!frames[@]}"; do
    d=4
    if [ "$i" -eq 0 ] || [ "$i" -eq $((n - 1)) ]; then d=3; fi
    printf "file '%s'\nduration %s\n" "${frames[$i]}" "$d" >> "$tmp/list.txt"
done
printf "file '%s'\n" "${frames[$((n - 1))]}" >> "$tmp/list.txt"

# 6. one palette for every frame, no dithering: flat colours, crisp text, small file
ffmpeg -loglevel error -y -f concat -safe 0 -i "$tmp/list.txt" \
    -vf "split[a][b];[a]palettegen=max_colors=96:stats_mode=full:reserve_transparent=0[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
    -fps_mode vfr -loop 0 "$tmp/raw.gif"

# 7. drop the extra 0.04 s frame that the repeated last file adds
magick "$tmp/raw.gif" -delete "$n" "$tmp/out.gif"
got=$(magick identify -format '%n\n' "$tmp/out.gif" | head -1)
[ "$got" -eq "$n" ] || { echo "render-gif: expected $n frames, got $got" >&2; exit 1; }

mkdir -p "$(dirname "$out")"
mv "$tmp/out.gif" "$out"
echo "render-gif: $out ($n slides, ${WIDTH}px wide, $(wc -c < "$out" | tr -d ' ') bytes)"
