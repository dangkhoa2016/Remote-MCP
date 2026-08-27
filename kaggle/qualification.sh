#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"
export MAX_BATCH_ESTIMATED_TOKENS="${MAX_BATCH_ESTIMATED_TOKENS:-512}"
export KAGGLE_INPUT_ROOT="${KAGGLE_INPUT_ROOT:-/kaggle/input}"

WORK_ROOT=""
ACCEPTANCE_5K=""
ACCEPTANCE_100K=""
ENABLE_CLOUDFLARE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --work-root) WORK_ROOT="$2"; shift 2 ;;
    --acceptance-5k) ACCEPTANCE_5K="$2"; shift 2 ;;
    --acceptance-100k) ACCEPTANCE_100K="$2"; shift 2 ;;
    --enable-cloudflare) ENABLE_CLOUDFLARE="$2"; shift 2 ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$WORK_ROOT" && -n "$ACCEPTANCE_5K" && -n "$ACCEPTANCE_100K" ]] || {
  echo "usage: $0 --work-root DIR --acceptance-5k DIR --acceptance-100k DIR --enable-cloudflare 0|1" >&2
  exit 2
}
[[ "$ENABLE_CLOUDFLARE" == "0" || "$ENABLE_CLOUDFLARE" == "1" ]] || { echo "ERROR: --enable-cloudflare must be 0 or 1" >&2; exit 2; }
[[ -d "$ACCEPTANCE_5K" && -d "$ACCEPTANCE_100K" ]] || { echo "ERROR: acceptance evidence directory missing" >&2; exit 2; }

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
QUAL_DIR="$WORK_ROOT/qualification-$STAMP"
MATRIX_DIR="$QUAL_DIR/hardware-cases"
mkdir -p "$QUAL_DIR" "$MATRIX_DIR"
SERVER_PID=""
SERVER_LOG=""
EXT_WORK=""
EXTERNAL_KEY=""
GPU_TELEMETRY_PID=""
PROCESS_TELEMETRY_PID=""

cleanup_server() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  SERVER_PID=""
}

start_telemetry() {
  nohup nvidia-smi \
    --query-gpu=timestamp,index,name,pstate,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu,clocks.sm,clocks.mem \
    --format=csv,noheader,nounits -l 1 > "$QUAL_DIR/gpu-telemetry.csv" 2> "$QUAL_DIR/gpu-telemetry.stderr.log" &
  GPU_TELEMETRY_PID=$!
  nohup bash -c '
    while true; do
      printf "TIMESTAMP_UTC=%s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      ps -eo pid,ppid,psr,pcpu,pmem,rss,vsz,nlwp,etimes,stat,comm,args \
        | grep -E "PID|python|uvicorn|benchmark|cloudflared" | grep -v grep || true
      echo "---"
      sleep 1
    done
  ' > "$QUAL_DIR/process-telemetry.log" 2> "$QUAL_DIR/process-telemetry.stderr.log" &
  PROCESS_TELEMETRY_PID=$!
}

stop_telemetry() {
  for pid in "$GPU_TELEMETRY_PID" "$PROCESS_TELEMETRY_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  GPU_TELEMETRY_PID=""
  PROCESS_TELEMETRY_PID=""
}

cleanup_all() {
  set +e
  if [[ -n "$EXT_WORK" && -d "$EXT_WORK" ]]; then
    EXPOSE_MODE=cloudflare-quick WORKING_DIR="$EXT_WORK" bash scripts/expose-cloudflare.sh stop >/dev/null 2>&1 || true
  fi
  cleanup_server
  stop_telemetry
}
trap cleanup_all EXIT INT TERM

write_status() {
  local path="$1" status="$2" detail="${3:-}"
  python - "$path" "$status" "$detail" <<'PYSTATUS'
import json, sys
path, status, detail = sys.argv[1:]
out = {'status': status}
if detail:
    out['detail'] = detail
open(path, 'w', encoding='utf-8').write(json.dumps(out, indent=2, sort_keys=True) + '\n')
PYSTATUS
}

acceptance_status() {
  python - "$1/final-acceptance.json" <<'PYSTATUS'
import json, sys
try:
    data=json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    print('MISSING')
else:
    print(data.get('status') or data.get('FINAL_ACCEPTANCE') or 'UNKNOWN')
PYSTATUS
}

wait_ready() {
  local url="$1" key_file="${2:-}" code="" auth_conf=""
  for _ in $(seq 1 180); do
    if [[ -n "$key_file" && -r "$key_file" ]]; then
      auth_conf="${key_file}.ready-curl.conf"
      umask 077
      printf 'header = "Authorization: Bearer %s"\n' "$(cat "$key_file")" > "$auth_conf"
      code="$(curl -sS -o /dev/null -w '%{http_code}' --config "$auth_conf" "$url/ready" 2>/dev/null || true)"
      rm -f "$auth_conf"
    else
      code="$(curl -sS -o /dev/null -w '%{http_code}' "$url/ready" 2>/dev/null || true)"
    fi
    [[ "$code" == "200" ]] && return 0
    sleep 2
  done
  echo "ERROR: readiness timeout for $url" >&2
  return 1
}

start_local_server() {
  local workers="$1" port="$2" index_dir="$3" log_name="$4"
  cleanup_server
  SERVER_LOG="$QUAL_DIR/$log_name"
  API_KEY='' EXPOSE_MODE=off WORKING_DIR="$WORK_ROOT/local-runtime-w${workers}" \
    WORKER_COUNT="$workers" PORT="$port" SEARCH_INDEX_DIR="$index_dir" \
    bash kaggle/run-demo.sh >"$SERVER_LOG" 2>&1 &
  SERVER_PID=$!
  wait_ready "http://127.0.0.1:$port"
}

index_dir_from_acceptance() {
  local evidence="$1" path
  [[ -s "$evidence/index-path.txt" ]] || { echo "ERROR: acceptance evidence missing index-path.txt: $evidence" >&2; return 1; }
  path="$(head -1 "$evidence/index-path.txt")"
  [[ -f "$path/index-metadata.json" && -f "$path/vectors.npy" && -f "$path/rows.json" ]] || {
    echo "ERROR: proven 100K index is incomplete at $path" >&2; return 1;
  }
  printf '%s\n' "$path"
}

# STAGE_0_STATIC_PREFLIGHT
write_status "$QUAL_DIR/stage-0-static-preflight.json" "MEASURED" "running"
python -m pytest -q > "$QUAL_DIR/static-pytest.log" 2>&1
python -m compileall -q app benchmark dataset scripts
bash -n kaggle/run-demo.sh kaggle/acceptance.sh kaggle/qualification.sh scripts/smoke-test.sh scripts/expose-cloudflare.sh
python -m json.tool kaggle/demo.ipynb >/dev/null
git diff --check
write_status "$QUAL_DIR/stage-0-static-preflight.json" "PASS"

# STAGE_1_5K_ACCEPTANCE
STATUS_5K="$(acceptance_status "$ACCEPTANCE_5K")"
[[ "$STATUS_5K" == "PASS" ]] || { write_status "$QUAL_DIR/stage-1-5k-acceptance.json" "FAIL" "$STATUS_5K"; echo "ERROR: 5K acceptance is not PASS" >&2; exit 20; }
write_status "$QUAL_DIR/stage-1-5k-acceptance.json" "PASS"

# STAGE_2_100K_ACCEPTANCE
STATUS_100K="$(acceptance_status "$ACCEPTANCE_100K")"
[[ "$STATUS_100K" == "PASS" ]] || { write_status "$QUAL_DIR/stage-2-100k-acceptance.json" "FAIL" "$STATUS_100K"; echo "ERROR: 100K acceptance is not PASS; refusing Stage 3+" >&2; exit 21; }
INDEX_DIR="$(index_dir_from_acceptance "$ACCEPTANCE_100K")"
printf '%s\n' "$INDEX_DIR" > "$QUAL_DIR/index-path.txt"
cp "$ACCEPTANCE_100K/index-metadata.json" "$QUAL_DIR/index-metadata.json"
write_status "$QUAL_DIR/stage-2-100k-acceptance.json" "PASS"
start_telemetry

# STAGE_3_MODEL_CAPABILITIES
start_local_server 2 8000 "$INDEX_DIR" "stage-3-dual-server.log"
python scripts/qualification-semantic.py --url http://127.0.0.1:8000 --index-dir "$INDEX_DIR" --output "$QUAL_DIR/semantic-quality.json"
python scripts/qualification-dataset.py --output "$QUAL_DIR/dataset-quality.json"
python scripts/qualification-model.py --url http://127.0.0.1:8000 --index-dir "$INDEX_DIR" --output "$QUAL_DIR/model-capabilities.json"
cleanup_server
write_status "$QUAL_DIR/stage-3-model-capabilities.json" "PASS"

# STAGE_4_HARDWARE_ENVELOPE
python - "$MATRIX_DIR/matrix-spec.json" <<'PYMATRIXSPEC'
import json, sys
from dataclasses import asdict
from benchmark.matrix import default_matrix
open(sys.argv[1], 'w', encoding='utf-8').write(json.dumps([asdict(c) for c in default_matrix()], indent=2, sort_keys=True) + '\n')
PYMATRIXSPEC
for workers in 1 2; do
  port=$((8010 + workers))
  start_local_server "$workers" "$port" '' "stage-4-w${workers}-server.log"
  python - "$workers" "$MATRIX_DIR" "$port" <<'PYMATRIX'
import json, subprocess, sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import httpx
from benchmark.matrix import default_matrix
workers=int(sys.argv[1]); root=Path(sys.argv[2]); port=int(sys.argv[3]); url=f'http://127.0.0.1:{port}'
with httpx.Client(timeout=30.0) as client:
    for case in default_matrix():
        if case.worker_count != workers:
            continue
        out=root/f'{case.id}.json'
        before=client.get(f'{url}/metrics').json()
        started=datetime.now(timezone.utc).isoformat()
        cmd=[sys.executable,'-m','benchmark.benchmark','--url',url,
             '--requests',str(case.requests),'--concurrency',str(case.concurrency),
             '--items-per-request',str(case.items_per_request),'--dimensions',str(case.dimensions),
             '--label',case.id,'--output',str(out)]
        rc=subprocess.run(cmd, check=False).returncode
        ended=datetime.now(timezone.utc).isoformat()
        after=client.get(f'{url}/metrics').json()
        if not out.exists():
            out.write_text(json.dumps({'errors':case.requests}, indent=2)+'\n', encoding='utf-8')
        data=json.loads(out.read_text(encoding='utf-8'))
        data.update(asdict(case))
        data['case_id']=case.id
        data['benchmark_exit_code']=rc
        data['started_utc']=started
        data['ended_utc']=ended
        data['rejected_429']=max(0, int(after.get('rejected_429',0))-int(before.get('rejected_429',0)))
        data['metrics_after_case']=after
        out.write_text(json.dumps(data, indent=2, sort_keys=True)+'\n', encoding='utf-8')
        with (root/f'{case.id}.nvidia-smi.txt').open('w', encoding='utf-8') as handle:
            subprocess.run(['nvidia-smi'], stdout=handle, stderr=subprocess.STDOUT, check=False, text=True)
PYMATRIX
  cleanup_server
done
python scripts/qualification-hardware.py --input "$MATRIX_DIR" --output "$QUAL_DIR/hardware-envelope.json"
python scripts/qualification-long-context.py --output "$QUAL_DIR/long-context-envelope.json" || {
  echo "ERROR: long-context probe failed before establishing a measured envelope" >&2
  exit 22
}
write_status "$QUAL_DIR/stage-4-hardware-envelope.json" "MEASURED"

# STAGE_5_EXTERNAL_SECURITY
if [[ "$ENABLE_CLOUDFLARE" == "0" ]]; then
  write_status "$QUAL_DIR/external-security-status.json" "SKIPPED_OPT_IN"
else
  command -v cloudflared >/dev/null 2>&1 || { echo "ERROR: cloudflared executable not found for opt-in Stage 5" >&2; exit 25; }
  {
    printf 'cloudflared_path=%s\n' "$(command -v cloudflared)"
    cloudflared --version
  } > "$QUAL_DIR/cloudflared-version.txt"
  EXT_WORK="$WORK_ROOT/external-demo-$STAMP"
  mkdir -p "$EXT_WORK"
  KEY_FILE="$EXT_WORK/secrets/api-key"
  API_KEY='' EXPOSE_MODE=cloudflare-quick WORKING_DIR="$EXT_WORK" API_KEY_FILE="$KEY_FILE" \
    WORKER_COUNT=2 PORT=8020 SEARCH_INDEX_DIR="$INDEX_DIR" \
    bash kaggle/run-demo.sh > "$EXT_WORK/server.log" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 120); do [[ -s "$KEY_FILE" ]] && break; sleep 1; done
  [[ -s "$KEY_FILE" ]] || { echo "ERROR: external server did not create ephemeral key" >&2; exit 23; }
  wait_ready http://127.0.0.1:8020 "$KEY_FILE"
  EXTERNAL_KEY="$(cat "$KEY_FILE")"
  EXPOSE_MODE=cloudflare-quick WORKING_DIR="$EXT_WORK" API_KEY_FILE="$KEY_FILE" LOCAL_URL=http://127.0.0.1:8020 \
    bash scripts/expose-cloudflare.sh start > "$EXT_WORK/expose-start.log"
  URL_FILE="$EXT_WORK/cloudflare/tunnel-url.txt"
  [[ -s "$URL_FILE" ]] || { echo "ERROR: Quick Tunnel URL file missing" >&2; exit 24; }
  TUNNEL_URL="$(head -1 "$URL_FILE")"

  QWEN_EXTERNAL_KEY="$EXTERNAL_KEY" QWEN_TUNNEL_URL="$TUNNEL_URL" python - "$QUAL_DIR" <<'PYREMOTE'
import json, os, sys
from pathlib import Path
import httpx
root=Path(sys.argv[1]); key=os.environ['QWEN_EXTERNAL_KEY']; url=os.environ['QWEN_TUNNEL_URL'].rstrip('/')
with httpx.Client(timeout=120.0) as client:
    health=client.get(url+'/health')
    noauth=client.get(url+'/ready')
    wrong=client.get(url+'/ready', headers={'Authorization':'Bearer wrong'})
    valid=client.get(url+'/ready', headers={'Authorization':f'Bearer {key}'})
    auth_matrix={
        'health_http_status':health.status_code,
        'missing_auth_http_status':noauth.status_code,
        'wrong_auth_http_status':wrong.status_code,
        'valid_auth_http_status':valid.status_code,
    }
    expected={'health_http_status':200,'missing_auth_http_status':401,'wrong_auth_http_status':401,'valid_auth_http_status':200}
    if auth_matrix != expected:
        raise SystemExit(f'external auth matrix failed: {auth_matrix}')
    embedding=client.post(url+'/v1/embeddings', headers={'Authorization':f'Bearer {key}'}, json={
        'model':'qwen3-embedding-8b-kaggle','input':['Berlin is the capital of Germany.'],'dimensions':1024})
    embedding.raise_for_status()
    search=client.post(url+'/v1/search', headers={'Authorization':f'Bearer {key}'}, json={
        'query':'thủ đô hiện nay của Đức','top_k':10,'language':'vi'})
    search.raise_for_status()
    (root/'external-embedding.json').write_text(json.dumps(embedding.json(),ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    (root/'external-search.json').write_text(json.dumps(search.json(),ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    (root/'external-ready.json').write_text(json.dumps(valid.json(),indent=2,sort_keys=True)+'\n',encoding='utf-8')
    (root/'external-auth-matrix.json').write_text(json.dumps(auth_matrix,indent=2,sort_keys=True)+'\n',encoding='utf-8')
PYREMOTE
  python - "$QUAL_DIR/external-url-proof.json" "$TUNNEL_URL" <<'PYURL'
import hashlib, json, sys
url=sys.argv[2]
out={'status':'PASS','tunnel_provider':'cloudflare-quick','tunnel_url_sha256':hashlib.sha256(url.encode()).hexdigest()}
open(sys.argv[1],'w',encoding='utf-8').write(json.dumps(out,indent=2,sort_keys=True)+'\n')
PYURL
  QWEN_SECRET="$EXTERNAL_KEY" python - "$QUAL_DIR" "$EXT_WORK" "$KEY_FILE" <<'PYSCAN'
import json, os, sys
from pathlib import Path
from app.qualification.evidence import scan_secret_bytes
qual=Path(sys.argv[1]); ext=Path(sys.argv[2]); key_file=Path(sys.argv[3]).resolve()
paths=[p for root in (qual,ext) for p in root.rglob('*') if p.is_file() and p.resolve()!=key_file]
matches=scan_secret_bytes(paths, os.environ['QWEN_SECRET'])
if matches:
    raise SystemExit('secret detected in logs/evidence files: '+', '.join(str(p) for p in matches))
(qual/'external-secret-scan.json').write_text(json.dumps({'secret_scan_status':'PASS','files_scanned':len(paths)},indent=2,sort_keys=True)+'\n',encoding='utf-8')
PYSCAN
  EXPOSE_MODE=cloudflare-quick WORKING_DIR="$EXT_WORK" API_KEY_FILE="$KEY_FILE" bash scripts/expose-cloudflare.sh stop >/dev/null
  QWEN_TUNNEL_URL="$TUNNEL_URL" python - "$QUAL_DIR/external-stale-url.json" <<'PYSTALE'
import json, os, sys, time
import httpx
url=os.environ['QWEN_TUNNEL_URL'].rstrip('/')
stale_url_reachable=True
last_status=None
for _ in range(10):
    try:
        response=httpx.get(url+'/health', timeout=5.0)
        last_status=response.status_code
        stale_url_reachable=(response.status_code==200)
    except Exception:
        stale_url_reachable=False
        last_status=None
    if not stale_url_reachable:
        break
    time.sleep(2)
if stale_url_reachable:
    raise SystemExit('Quick Tunnel URL still served /health after stop')
open(sys.argv[1],'w',encoding='utf-8').write(json.dumps({'stale_url_reachable':False,'last_http_status':last_status},indent=2,sort_keys=True)+'\n')
PYSTALE
  cleanup_server
  python - "$QUAL_DIR/external-security-status.json" <<'PYEXTERNALSTATUS'
import json, sys
out={'status':'PASS','auth_matrix':'PASS','secret_scan_status':'PASS','stale_url_reachable':False,'tunnel_stopped':True}
open(sys.argv[1],'w',encoding='utf-8').write(json.dumps(out,indent=2,sort_keys=True)+'\n')
PYEXTERNALSTATUS
fi

stop_telemetry
sleep 1

python - "$QUAL_DIR" "$STAMP" "$ACCEPTANCE_100K" <<'PYMANIFEST'
import json, os, sys
from pathlib import Path
from app.qualification.evidence import sanitize_runtime_config, sha256_file, sha256_json, write_manifest_v2
root=Path(sys.argv[1]); run_id=sys.argv[2]; acc=Path(sys.argv[3])
acc_manifest=json.loads((acc/'run-manifest.json').read_text(encoding='utf-8'))
semantic=Path('fixtures/semantic-golden/suite-v1.json')
code_a=Path('fixtures/code-retrieval/snippets-v1.json'); code_b=Path('fixtures/code-retrieval/queries-v1.json')
identity={
  'git_head':__import__('subprocess').check_output(['git','rev-parse','HEAD'], text=True).strip(),
  'model_fingerprint':acc_manifest['model_fingerprint'],
  'dataset_sha256':acc_manifest['dataset_sha256'],
  'index_metadata_sha256':sha256_file(root/'index-metadata.json'),
  'semantic_suite_sha256':sha256_file(semantic),
  'code_fixture_sha256':sha256_json({'snippets':sha256_file(code_a),'queries':sha256_file(code_b)}),
}
write_manifest_v2(root, run_id=run_id, run_kind='qualification', identity=identity, runtime_config=sanitize_runtime_config(os.environ))
PYMANIFEST
(
  cd "$QUAL_DIR"
  find . -type f ! -name SHA256SUMS -printf '%P\n' | sort | while IFS= read -r f; do sha256sum "$f"; done > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)
QUAL_ARCHIVE="$WORK_ROOT/qwen3-embedding-8b-t4x2-qualification-$STAMP.tar.gz"
tar -C "$WORK_ROOT" -czf "$QUAL_ARCHIVE" "$(basename "$QUAL_DIR")"
sha256sum "$QUAL_ARCHIVE" > "$QUAL_ARCHIVE.sha256"

echo "QUALIFICATION_DIR=$QUAL_DIR"
echo "QUALIFICATION_ARCHIVE=$QUAL_ARCHIVE"
echo "QUALIFICATION_SHA256=$QUAL_ARCHIVE.sha256"
echo "QUALIFICATION_COMPLETE=PASS"
