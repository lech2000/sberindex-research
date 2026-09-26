#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$ROOT/raw/hse-population-grid"
DEST="$OUT_DIR/GHS-POP_2021_corrected_for_Russia_HSE.zip"
TEMP="$OUT_DIR/GHS-POP_2021_corrected_for_Russia_HSE.parallel.part"
URL="https://geoportal.hse.ru/portal/sharing/rest/content/items/9ee9d4ad2b124f82949f9f061e0b42c9/data"
TOTAL_BYTES=231993832
CHUNK_MIB=28
CHUNK_BYTES=$((CHUNK_MIB * 1048576))

mkdir -p "$OUT_DIR"
truncate -s "$TOTAL_BYTES" "$TEMP"

pids=()
for i in 0 1 2 3 4 5 6 7; do
  start=$((i * CHUNK_BYTES))
  end=$((start + CHUNK_BYTES - 1))
  if (( end >= TOTAL_BYTES )); then
    end=$((TOTAL_BYTES - 1))
  fi
  echo "Starting byte range $start-$end"
  (
    curl -fsSL --retry 4 --retry-delay 2 --range "$start-$end" "$URL" |
      dd of="$TEMP" bs=1048576 seek=$((start / 1048576)) conv=notrunc status=none
    echo "Finished byte range $start-$end"
  ) &
  pids+=("$!")
done

for pid in "${pids[@]}"; do
  wait "$pid"
done

actual_bytes="$(stat -f '%z' "$TEMP")"
if [[ "$actual_bytes" != "$TOTAL_BYTES" ]]; then
  echo "Size mismatch: expected $TOTAL_BYTES, got $actual_bytes" >&2
  exit 1
fi

unzip -t "$TEMP"
mv -f "$TEMP" "$DEST"
openssl dgst -sha256 "$DEST"
echo "Downloaded and verified ZIP structure: $DEST"
