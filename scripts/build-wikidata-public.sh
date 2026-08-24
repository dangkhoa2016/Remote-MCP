#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${WIKIMEDIA_USER_AGENT:?Set WIKIMEDIA_USER_AGENT to a descriptive bot/tool User-Agent with contact info}"

OUTPUT_DIR="${1:-$ROOT/.artifacts/wikidata-en-vi-semantic-search-100k}"
WORK_DIR="${2:-$ROOT/.cache/wikidata-en-vi-acquisition}"
TARGET_ROWS="${TARGET_ROWS:-100000}"
DISCOVERY_PAGE_SIZE="${DISCOVERY_PAGE_SIZE:-250}"
ENTITY_BATCH_SIZE="${ENTITY_BATCH_SIZE:-50}"
OVERFETCH_FACTOR="${OVERFETCH_FACTOR:-1.35}"
MAX_DISCOVERY_FACTOR="${MAX_DISCOVERY_FACTOR:-2.5}"
MIN_REQUEST_INTERVAL="${MIN_REQUEST_INTERVAL:-0.35}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-60}"
KAGGLE_OWNER="${KAGGLE_OWNER:-dangkhoa2016}"
KAGGLE_SLUG="${KAGGLE_SLUG:-wikidata-en-vi-semantic-search-100k}"
KAGGLE_TITLE="${KAGGLE_TITLE:-Wikidata EN-VI Semantic Search 100K}"

mkdir -p "$OUTPUT_DIR" "$WORK_DIR"

python -m dataset.build_public_wikidata \
  --output-dir "$OUTPUT_DIR" \
  --work-dir "$WORK_DIR" \
  --target-rows "$TARGET_ROWS" \
  --user-agent "$WIKIMEDIA_USER_AGENT" \
  --discovery-page-size "$DISCOVERY_PAGE_SIZE" \
  --entity-batch-size "$ENTITY_BATCH_SIZE" \
  --overfetch-factor "$OVERFETCH_FACTOR" \
  --max-discovery-factor "$MAX_DISCOVERY_FACTOR" \
  --min-request-interval "$MIN_REQUEST_INTERVAL" \
  --timeout-seconds "$TIMEOUT_SECONDS" \
  --kaggle-owner "$KAGGLE_OWNER" \
  --kaggle-slug "$KAGGLE_SLUG" \
  --kaggle-title "$KAGGLE_TITLE"

printf 'DATASET_OUTPUT=%s\n' "$OUTPUT_DIR"
printf 'RESUME_WORK_DIR=%s\n' "$WORK_DIR"
printf 'KAGGLE_CREATE_HINT=kaggle datasets create -p %q\n' "$OUTPUT_DIR"
