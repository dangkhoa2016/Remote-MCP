#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"
export MAX_BATCH_ESTIMATED_TOKENS="${MAX_BATCH_ESTIMATED_TOKENS:-512}"
export KAGGLE_INPUT_ROOT="${KAGGLE_INPUT_ROOT:-/kaggle/input}"
export EXPOSE_MODE=off
EVIDENCE_SECRET_SCAN="${API_KEY:-}"
unset API_KEY || true

WORK_BASE="${WORKING_DIR:-/kaggle/working/qwen3-embedding-8b-t4x2}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_KIND="100k"
if [[ -n "${DEMO_CORPUS_LIMIT:-}" ]]; then RUN_KIND="5k"; fi
EVIDENCE="$WORK_BASE/evidence-$STAMP"
INDEX_DIR="${SEARCH_INDEX_DIR:-$WORK_BASE/index}"
mkdir -p "$EVIDENCE" "$WORK_BASE"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

wait_ready() {
  local url="$1" tries="${2:-180}"
  for ((i=1;i<=tries;i++)); do
    if curl -fsS "$url/ready" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  echo "ERROR: readiness timeout for $url" >&2
  return 1
}

start_server() {
  local workers="$1" port="$2" search_index="${3:-}"
  cleanup
  SERVER_PID=""
  API_KEY='' EXPOSE_MODE=off WORKER_COUNT="$workers" PORT="$port" SEARCH_INDEX_DIR="$search_index" \
    bash kaggle/run-demo.sh >"$EVIDENCE/server-w${workers}-p${port}.log" 2>&1 &
  SERVER_PID=$!
  wait_ready "http://127.0.0.1:$port"
}

{
  echo "DATE_UTC=$(date -u +%FT%TZ)"
  python -V
  uname -a
} > "$EVIDENCE/environment.txt"

python - <<'PY' > "$EVIDENCE/runtime-config.json"
import json, os
from app.qualification.evidence import sanitize_runtime_config
print(json.dumps(sanitize_runtime_config(os.environ), indent=2, sort_keys=True))
PY

{
  echo "branch=$(git branch --show-current)"
  echo "head=$(git rev-parse HEAD)"
  echo "status_begin"
  git status --short
  echo "status_end"
} > "$EVIDENCE/git-identity.txt"
python -m pip list --format=json > "$EVIDENCE/pip-list.json"
python - <<'PYDEP' > "$EVIDENCE/dependency-versions.txt"
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
packages = [
    ("torch", "torch"), ("transformers", "transformers"), ("accelerate", "accelerate"),
    ("bitsandbytes", "bitsandbytes"), ("safetensors", "safetensors"),
    ("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("httpx", "httpx"),
    ("numpy", "numpy"), ("faiss", "faiss-cpu"), ("pyarrow", "pyarrow"),
]
for module_name, distribution in packages:
    module = import_module(module_name)
    try:
        installed = version(distribution)
    except PackageNotFoundError:
        installed = getattr(module, "__version__", "unknown")
    print(f"{module_name}={installed}")
PYDEP
printf '%s\n' "$INDEX_DIR" > "$EVIDENCE/index-path.txt"
printf '%s\n' "$RUN_KIND" > "$EVIDENCE/run-kind.txt"

nvidia-smi > "$EVIDENCE/nvidia-smi-before.txt"
GPU_COUNT="$(nvidia-smi --query-gpu=name --format=csv,noheader | wc -l | tr -d ' ')"
[[ "$GPU_COUNT" -ge 2 ]] || { echo "ERROR: T4x2 acceptance requires two GPUs, found $GPU_COUNT" >&2; exit 10; }

python - <<'PY' | tee "$EVIDENCE/input-preflight.txt"
import os
from pathlib import Path
from app.model_resolver import resolve_kaggle_model_dir, model_fingerprint
from app.dataset_resolver import resolve_kaggle_dataset_dir, validate_dataset_dir
root=Path(os.environ.get('KAGGLE_INPUT_ROOT','/kaggle/input'))
model=resolve_kaggle_model_dir(root, os.environ.get('KAGGLE_MODEL_DIR'))
dataset=resolve_kaggle_dataset_dir(root, os.environ.get('KAGGLE_DATASET_DIR'))
manifest=validate_dataset_dir(dataset)
print('MODEL_SOURCE=kaggle_input')
print('MODEL_DIR='+str(model))
print('MODEL_FINGERPRINT='+model_fingerprint(model))
print('DATASET_DIR='+str(dataset))
print('DATASET_SOURCE='+manifest['source'])
print('DATASET_LICENSE='+manifest['source_license'])
print('DATASET_ROWS='+str(manifest['row_count']))
print('DATASET_CANONICAL_FILENAME='+str(manifest['canonical_filename']))
print('DATASET_CANONICAL_SHA256='+str(manifest['canonical_sha256']))
PY

python - <<'PY' | tee "$EVIDENCE/unicode-gate.txt"
import os
from pathlib import Path
from app.dataset_resolver import resolve_kaggle_dataset_dir, validate_dataset_dir
from app.unicode_quality import normalize_text
try:
    import pyarrow.parquet as pq
except ImportError as exc:
    raise SystemExit('pyarrow required for Unicode acceptance') from exc
root=Path(os.environ.get('KAGGLE_INPUT_ROOT','/kaggle/input'))
dir=resolve_kaggle_dataset_dir(root, os.environ.get('KAGGLE_DATASET_DIR'))
manifest=validate_dataset_dir(dir)
cols=['qid','label_en','label_vi','description_en','description_vi','document_en','document_vi']
table=pq.read_table(dir/manifest['canonical_filename'], columns=cols)
checked=0
flags=0
for row in table.to_pylist():
    for key in cols[1:]:
        value=row.get(key)
        if value is None: continue
        out=normalize_text(value)
        if out.text != value:
            raise SystemExit(f'non-canonical Unicode in {row.get("qid")}:{key}')
        flags += len(out.flags)
    checked += 1
print(f'UNICODE_ROWS_CHECKED={checked}')
print(f'UNICODE_FLAGS_REPORTED={flags}')
print('UNICODE_QUALITY_GATE=PASS')
PY

BUILD_LIMIT_ARGS=()
if [[ -n "${DEMO_CORPUS_LIMIT:-}" ]]; then BUILD_LIMIT_ARGS=(--limit "$DEMO_CORPUS_LIMIT"); fi
if [[ ! -f "$INDEX_DIR/index-metadata.json" || "${FORCE_REBUILD_INDEX:-0}" == "1" ]]; then
  WORKER_COUNT=2 SEARCH_INDEX_DIR='' python scripts/build-index.py \
    --output-dir "$INDEX_DIR" "${BUILD_LIMIT_ARGS[@]}" \
    2>&1 | tee "$EVIDENCE/index-build.log"
else
  echo "REUSING_INDEX=$INDEX_DIR" | tee "$EVIDENCE/index-build.log"
fi
cp "$INDEX_DIR/index-metadata.json" "$EVIDENCE/index-metadata.json"

# Single-GPU baseline.
start_server 1 8001 ''
SMOKE_SEARCH=0 bash scripts/smoke-test.sh http://127.0.0.1:8001 > "$EVIDENCE/smoke-single.txt"
python -m benchmark.benchmark --url http://127.0.0.1:8001 --requests "${BENCH_REQUESTS:-16}" \
  --concurrency "${BENCH_SINGLE_CONCURRENCY:-2}" --items-per-request "${BENCH_ITEMS_PER_REQUEST:-8}" \
  --dimensions "${BENCH_DIMENSIONS:-1024}" --label single --output "$EVIDENCE/benchmark-single.json"
cleanup; SERVER_PID=""

# Two independent T4 replicas + search index.
start_server 2 8000 "$INDEX_DIR"
bash scripts/smoke-test.sh http://127.0.0.1:8000 | tee "$EVIDENCE/smoke-dual.txt"
python -m benchmark.benchmark --url http://127.0.0.1:8000 --requests "${BENCH_REQUESTS:-16}" \
  --concurrency "${BENCH_DUAL_CONCURRENCY:-4}" --items-per-request "${BENCH_ITEMS_PER_REQUEST:-8}" \
  --dimensions "${BENCH_DIMENSIONS:-1024}" --label dual --output "$EVIDENCE/benchmark-dual.json"
curl -fsS http://127.0.0.1:8000/metrics | python -m json.tool > "$EVIDENCE/metrics.json"
curl -fsS http://127.0.0.1:8000/info | python -m json.tool > "$EVIDENCE/info.json"
curl -fsS -H 'Content-Type: application/json' -d '{"query":"thủ đô của Đức","top_k":10,"language":"vi"}' \
  http://127.0.0.1:8000/v1/search | python -m json.tool > "$EVIDENCE/search-vi.json"

python - "$EVIDENCE" <<'PY'
from pathlib import Path
import json, sys
p=Path(sys.argv[1])
single=json.loads((p/'benchmark-single.json').read_text())
dual=json.loads((p/'benchmark-dual.json').read_text())
metrics=json.loads((p/'metrics.json').read_text())
search=json.loads((p/'search-vi.json').read_text())
batches=metrics.get('batches_per_worker', {})
active=[k for k,v in batches.items() if int(v)>0]
if len(active) < 2:
    raise SystemExit(f'dual-GPU activity not proven: batches_per_worker={batches}')
if not search.get('data'):
    raise SystemExit('semantic search returned no results')
ratio=dual['throughput_items_per_second']/single['throughput_items_per_second'] if single['throughput_items_per_second'] else 0.0
summary={
  'status':'PASS',
  'model_source':'kaggle_input',
  'gpu_workers_ready':2,
  'active_worker_ids':active,
  'single_items_per_second':single['throughput_items_per_second'],
  'dual_items_per_second':dual['throughput_items_per_second'],
  'measured_throughput_ratio':round(ratio,6),
  'semantic_top_qid':search['data'][0].get('qid'),
  'performance_threshold_enforced':False,
}
(p/'final-acceptance.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
print(json.dumps(summary,indent=2,sort_keys=True))
PY

nvidia-smi > "$EVIDENCE/nvidia-smi-after.txt"
cleanup; SERVER_PID=""

if [[ -n "$EVIDENCE_SECRET_SCAN" ]]; then
  QWEN_EVIDENCE_SECRET_SCAN="$EVIDENCE_SECRET_SCAN" python - "$EVIDENCE" <<'PY'
import os, sys
from pathlib import Path
from app.qualification.evidence import scan_secret_bytes
root=Path(sys.argv[1])
matches=scan_secret_bytes([p for p in root.iterdir() if p.is_file()], os.environ['QWEN_EVIDENCE_SECRET_SCAN'])
if matches:
    raise SystemExit('secret detected in evidence files: ' + ', '.join(p.name for p in matches))
PY
fi

python - "$EVIDENCE" "$STAMP" "$RUN_KIND" <<'PY'
from hashlib import sha256
import json, os, sys
from pathlib import Path
from app.dataset_resolver import resolve_kaggle_dataset_dir, validate_dataset_dir
from app.model_resolver import resolve_kaggle_model_dir, model_fingerprint
from app.qualification.evidence import sanitize_runtime_config, sha256_file, sha256_json, write_manifest_v2
root=Path(sys.argv[1]); run_id=sys.argv[2]; run_kind=sys.argv[3]
input_root=Path(os.environ.get('KAGGLE_INPUT_ROOT','/kaggle/input'))
model=resolve_kaggle_model_dir(input_root, os.environ.get('KAGGLE_MODEL_DIR'))
dataset=resolve_kaggle_dataset_dir(input_root, os.environ.get('KAGGLE_DATASET_DIR'))
dm=validate_dataset_dir(dataset)
index_meta=root/'index-metadata.json'
semantic=Path('fixtures/semantic-golden/suite-v1.json')
code_a=Path('fixtures/code-retrieval/snippets-v1.json')
code_b=Path('fixtures/code-retrieval/queries-v1.json')
identity={
  'git_head': __import__('subprocess').check_output(['git','rev-parse','HEAD'], text=True).strip(),
  'model_fingerprint': model_fingerprint(model),
  'dataset_sha256': dm['canonical_sha256'],
  'index_metadata_sha256': sha256_file(index_meta),
  'semantic_suite_sha256': sha256_file(semantic),
  'code_fixture_sha256': sha256_json({'snippets':sha256_file(code_a),'queries':sha256_file(code_b)}),
}
write_manifest_v2(root, run_id=run_id, run_kind=run_kind, identity=identity, runtime_config=sanitize_runtime_config(os.environ))
PY
(
  cd "$EVIDENCE"
  find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%f\n' | sort | xargs sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)
ARCHIVE="$WORK_BASE/qwen3-embedding-8b-t4x2-acceptance-$STAMP.tar.gz"
tar -C "$WORK_BASE" -czf "$ARCHIVE" "$(basename "$EVIDENCE")"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"
echo "EVIDENCE_DIR=$EVIDENCE"
echo "EVIDENCE_ARCHIVE=$ARCHIVE"
echo "EVIDENCE_SHA256=$ARCHIVE.sha256"
echo "FINAL_ACCEPTANCE=PASS"
