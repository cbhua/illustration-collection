#!/usr/bin/env bash
# Batch-export every .graffle in a folder with OmniGraffle (macOS).  Usage: tools/og_export_all.sh DIR [pdf|png]
set -euo pipefail
dir="${1:?folder}"; fmt="${2:-pdf}"
here="$(cd "$(dirname "$0")" && pwd)"
find "$dir" -name '*.graffle' -print0 | while IFS= read -r -d '' f; do
  out="${f%.graffle}.$fmt"
  osascript "$here/og_export.applescript" "$(cd "$(dirname "$f")" && pwd)/$(basename "$f")" "$(cd "$(dirname "$out")" && pwd)/$(basename "$out")"
done
