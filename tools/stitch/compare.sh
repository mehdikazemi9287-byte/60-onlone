#!/usr/bin/env bash
# Side-by-side evidence image: Stitch design (left) vs the local page (right).
#   tools/stitch/compare.sh <stitch-screen.html|png> <page-url> <out.png> [width=1440|390] [height]
# Desktop screens use width 1440, mobile screens 390. Requires google-chrome and ImageMagick.
set -euo pipefail
SRC=$1; URL=$2; OUT=$3; W=${4:-1440}; H=${5:-$([ "$W" -lt 600 ] && echo 2600 || echo 2400)}
T=$(mktemp -d); HERE=$(cd "$(dirname "$0")" && pwd)
if [[ $SRC == *.html ]]; then node "$HERE/render.mjs" "$SRC" "$T/stitch.png" "$W" >/dev/null; else cp "$SRC" "$T/stitch.png"; fi
timeout 120 google-chrome --headless=new --no-sandbox --hide-scrollbars --window-size=$W,$H \
  --virtual-time-budget=8000 --screenshot="$T/page.png" "$URL" >/dev/null 2>&1
convert "$T/stitch.png" -resize ${W}x "$T/a.png"; convert "$T/page.png" -resize ${W}x "$T/b.png"
convert "$T/a.png" "$T/b.png" -background white -gravity north +append \
  -gravity north -splice 0x40 -pointsize 22 -annotate +0+8 "STITCH (left)   |   LOCAL PAGE (right)   $URL" "$OUT"
echo "$OUT"
