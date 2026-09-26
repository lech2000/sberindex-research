#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="$ROOT/raw/sberindex-data-sense-2025"
PUBLIC_KEY="https://disk.yandex.ru/d/WH8yJOogD4UrOg"

mkdir -p "$OUT"

download_one() {
  local name="$1"
  local expected_sha256="$2"
  local href

  href="$(curl -fsS --get \
    'https://cloud-api.yandex.net/v1/disk/public/resources/download' \
    --data-urlencode "public_key=$PUBLIC_KEY" \
    --data-urlencode "path=/$name" | jq -er '.href')"

  curl -fL --retry 3 --retry-delay 2 --continue-at - \
    --output "$OUT/$name" "$href"

  local actual_sha256
  actual_sha256="$(openssl dgst -sha256 "$OUT/$name" | awk '{print $NF}')"
  if [[ "$actual_sha256" != "$expected_sha256" ]]; then
    echo "Checksum mismatch for $name: expected $expected_sha256, got $actual_sha256" >&2
    return 1
  fi
  echo "$name: checksum OK"
}

download_one '1_market_access.parquet' '434258afe322b7e6e6610b2552d129ae47094613de72dae3d13f6965a28d1dc1'
download_one '2_bdmo_population.parquet' '4b69d43dd113591c12cee61df39d318200ff42b83e52a28593930e7ee0b34dbf'
download_one '3_bdmo_migration.parquet' 'a7bff6bbf0dbd0cc0a8c83283ddf4b4fd0a13bbff5773ea167e6b79f590c67db'
download_one '4_bdmo_salary.parquet' 'f9a8956ad68c7ec81fac7b2e61ac2494b02b489887ce06204621b5dff29e62f2'
download_one '5_connection.parquet' '696dbc891eff7566bed38a4607331da6fab56a233a562ee738f42813c008e79b'
download_one '8_consumption.parquet' '9833ddaaee7b2a182ed4cceeed16469031700ea87d508bd976150c6770ef8a61'
download_one 'basket_emiss_pars_hackathon.xlsx' '484383215903e3a1455e583c46ea8860f36ac873511bf36463b158ae4a11f0c0'
download_one 'Описание_данных_для_Хакатона_2025_6_6.docx' 'd2e462f22a2af8b0168eafef04d2fb554c902bea037a2d7ad92190201cb436d9'

echo "Downloaded and verified: $OUT"
