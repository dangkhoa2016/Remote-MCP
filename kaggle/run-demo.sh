#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"
export MAX_BATCH_ESTIMATED_TOKENS="${MAX_BATCH_ESTIMATED_TOKENS:-512}"
export KAGGLE_INPUT_ROOT="${KAGGLE_INPUT_ROOT:-/kaggle/input}"
export WORKER_COUNT="${WORKER_COUNT:-2}"
export PORT="${PORT:-8000}"
export EXPOSE_MODE="${EXPOSE_MODE:-off}"

if [[ "$EXPOSE_MODE" != "off" && "$EXPOSE_MODE" != "cloudflare-quick" ]]; then
  echo "ERROR: EXPOSE_MODE must be off or cloudflare-quick" >&2
  exit 2
fi

if [[ "$EXPOSE_MODE" == "cloudflare-quick" && -z "${API_KEY:-}" ]]; then
  SECRET_DIR="${WORKING_DIR:-/kaggle/working/qwen3-embedding-8b-t4x2}/secrets"
  API_KEY_FILE="${API_KEY_FILE:-$SECRET_DIR/api-key}"
  mkdir -p "$SECRET_DIR"
  umask 077
  python - <<'PY' > "$API_KEY_FILE"
import secrets
print(secrets.token_urlsafe(32))
PY
  chmod 600 "$API_KEY_FILE" 2>/dev/null || true
  export API_KEY="$(cat "$API_KEY_FILE")"
fi

[[ -d "$KAGGLE_INPUT_ROOT" ]] || { echo "ERROR: Kaggle input root not found: $KAGGLE_INPUT_ROOT" >&2; exit 2; }

python - <<'PY'
import importlib
import os
required = ['torch', 'transformers', 'bitsandbytes', 'fastapi', 'uvicorn', 'numpy']
if os.environ.get('SEARCH_INDEX_DIR'):
    required.append('faiss')
missing=[]
for name in required:
    try: importlib.import_module(name)
    except Exception as exc: missing.append(f'{name}: {exc}')
if missing:
    raise SystemExit('Missing Kaggle runtime dependencies:\n  - ' + '\n  - '.join(missing))

import torch
wanted=int(os.environ.get('WORKER_COUNT','2'))
count=torch.cuda.device_count()
print(f'CUDA_DEVICE_COUNT={count}', flush=True)
for i in range(count):
    print(f'GPU_{i}={torch.cuda.get_device_name(i)}', flush=True)
if count < wanted:
    raise SystemExit(f'Need at least {wanted} CUDA GPU(s), found {count}')
PY

python - <<'PY'
import os
from pathlib import Path
from app.model_resolver import resolve_kaggle_model_dir, model_fingerprint
root=Path(os.environ.get('KAGGLE_INPUT_ROOT','/kaggle/input'))
path=resolve_kaggle_model_dir(root, os.environ.get('KAGGLE_MODEL_DIR'))
print(f'MODEL_SOURCE=kaggle_input')
print(f'RESOLVED_MODEL_DIR={path}')
print(f'MODEL_FINGERPRINT={model_fingerprint(path)}')
PY

exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1
