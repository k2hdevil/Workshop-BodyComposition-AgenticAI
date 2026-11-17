#!/usr/bin/env bash
#
# Build the sample result sheet PDFs
#
#   ground-truth/*.json  (single source of truth)
#        -> html/*.html   (intermediate output, not tracked by git)
#        -> pdf/*.pdf     (distributed to participants)
#        -> documents marked as scans are reprocessed into image-only PDFs
#
# Usage:  ./tools/build_samples.sh
#
# Note: headless Chrome sometimes does not exit after it finishes a --print-to-pdf job
#       (observed with Chrome 151). So the script starts it in the background, treats the
#       moment the output file size becomes stable as success, and then kills only that instance.
#
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

GT_DIR="$ROOT/ground-truth"
HTML_DIR="$ROOT/html"
PDF_DIR="$ROOT/pdf"
mkdir -p "$HTML_DIR" "$PDF_DIR"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ ! -x "$CHROME" ]; then
  echo "error: Chrome not found — $CHROME" >&2
  exit 1
fi

# Use a dedicated temporary profile so it does not collide with the Chrome profile the user runs.
# Only processes that have this path on their command line are cleaned up, so the user's browser is safe.
PROFILE="$(mktemp -d)"
cleanup() {
  pkill -9 -f "user-data-dir=$PROFILE" 2>/dev/null || true
  rm -rf "$PROFILE"
}
trap cleanup EXIT

WAIT_MAX=45  # Maximum wait in seconds per PDF

render_pdf() {
  local html="$1" out="$2"
  rm -f "$out"

  "$CHROME" \
    --headless=new \
    --disable-gpu \
    --disable-extensions \
    --user-data-dir="$PROFILE" \
    --no-pdf-header-footer \
    --virtual-time-budget=5000 \
    --print-to-pdf="$out" \
    "file://$html" >/dev/null 2>&1 &
  local pid=$!

  # Treat the write as complete once the file exists and its size is the same twice in a row
  local waited=0 prev=-1 size=0
  while [ "$waited" -lt "$WAIT_MAX" ]; do
    sleep 1
    waited=$((waited + 1))
    if [ -f "$out" ]; then
      size=$(wc -c <"$out" | tr -d ' ')
      if [ "$size" -gt 2000 ] && [ "$size" -eq "$prev" ]; then
        break
      fi
      prev=$size
    fi
  done

  kill -9 "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  pkill -9 -f "print-to-pdf=$out" 2>/dev/null || true

  if [ ! -f "$out" ] || [ "$(wc -c <"$out" | tr -d ' ')" -lt 2000 ]; then
    echo "  failed  $(basename "$out") — not created within ${WAIT_MAX} seconds" >&2
    return 1
  fi
  printf "  converted  %-24s %8s bytes\n" "$(basename "$out")" "$size"
}

echo "== 1/3  JSON -> HTML rendering =="
for json in "$GT_DIR"/*.json; do
  base="$(basename "$json" .json)"
  python3 tools/render_sheet.py "$json" "$HTML_DIR/$base.html"
done

echo "== 2/3  HTML -> PDF conversion (headless Chrome) =="
for html in "$HTML_DIR"/*.html; do
  base="$(basename "$html" .html)"
  render_pdf "$html" "$PDF_DIR/$base.pdf"
done

echo "== 3/3  Scan re-processing (remove the text layer) =="
python3 tools/make_scan.py

echo
echo "Build finished. Verify with:  python3 tools/verify_samples.py"
