#!/usr/bin/env bash
#
# Reproducible fresh-Kaggle bootstrap.
#
# Makes a brand-new Kaggle Notebook self-sufficient without manual diagnosis:
#   - nvidia-smi on PATH (absent by default on Kaggle)
#   - NVIDIA runtime libraries discoverable via LD_LIBRARY_PATH
#   - test/runtime dependencies installed only when missing
#   - the already-working CUDA Torch is NEVER replaced
#
# Safe on a re-run (idempotent): it always refuses to replace Torch.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

# --- 1/2/3. Make Kaggle GPU tooling discoverable without disturbing the rest.
if [[ -d /opt/bin ]]; then
  export PATH="/opt/bin${PATH:+:$PATH}"
fi
if [[ -d /opt/nvidia/bin ]]; then
  export PATH="/opt/nvidia/bin${PATH:+:$PATH}"
fi
if [[ -d /usr/local/nvidia/lib64 ]]; then
  export LD_LIBRARY_PATH="/usr/local/nvidia/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

# --- 4. Record package identity BEFORE any dependency work.
TORCH_VERSION_BEFORE="$(python - <<'PY'
import torch
print(torch.__version__)
PY
)"
TORCH_FILE_BEFORE="$(python - <<'PY'
import torch
print(torch.__file__)
PY
)"

echo "bootstrap: torch ${TORCH_VERSION_BEFORE} at ${TORCH_FILE_BEFORE} before dependency work"

# --- 5. Install test-only dependencies (never touches Torch).
if [[ -f "$ROOT/requirements-test.txt" ]]; then
  (cd "$ROOT" && python -m pip install -r requirements-test.txt)
fi

# --- 6/7. Install missing runtime requirements without replacing Torch.
# requirements-kaggle.txt intentionally contains NO Torch pin, so installing it
# cannot replace Kaggle's CUDA Torch. If a future writer adds one, we must refuse.
if [[ -f "$ROOT/requirements-kaggle.txt" ]]; then
  if grep -qiE '^\s*torch([<>=]=?)?\s' "$ROOT/requirements-kaggle.txt"; then
    echo "ERROR: requirements-kaggle.txt pins Torch; refusing to replace the working CUDA Torch stack." >&2
    exit 3
  fi
  python -m pip install -r "$ROOT/requirements-kaggle.txt"
fi

# --- 8. Verify Torch is bit-for-bit unchanged.
TORCH_VERSION_AFTER="$(python - <<'PY'
import torch
print(torch.__version__)
PY
)"
TORCH_FILE_AFTER="$(python - <<'PY'
import torch
print(torch.__file__)
PY
)"

test "$TORCH_VERSION_BEFORE" = "$TORCH_VERSION_AFTER" \
  || { echo "ERROR: Torch version changed during bootstrap (${TORCH_VERSION_BEFORE} -> ${TORCH_VERSION_AFTER})" >&2; exit 3; }
test "$TORCH_FILE_BEFORE" = "$TORCH_FILE_AFTER" \
  || { echo "ERROR: Torch file changed during bootstrap (${TORCH_FILE_BEFORE} -> ${TORCH_FILE_AFTER})" >&2; exit 3; }

# --- 9. Verify CUDA is usable with the adopted PATH/LD_LIBRARY_PATH.
python - <<'PY' || { echo "ERROR: torch.cuda.is_available() is False after bootstrap" >&2; exit 3; }
import torch
if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
    raise SystemExit(1)
print(f"cuda_available=True device_count={torch.cuda.device_count()}")
PY

# --- 10. Verify two T4 GPUs visible via nvidia-smi.
command -v nvidia-smi >/dev/null 2>&1 \
  || { echo "ERROR: nvidia-smi not on PATH after bootstrap" >&2; exit 4; }
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader \
  || { echo "ERROR: nvidia-smi failed" >&2; exit 4; }
GPU_COUNT="$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)"
if (( GPU_COUNT < 2 )); then
  echo "ERROR: expected at least 2 GPUs, found ${GPU_COUNT}" >&2
  exit 4
fi

# --- 11. Emit exact dependency versions.
python - <<'PY'
import importlib
# (label, import_name)
packages = [
    ('torch', 'torch'), ('transformers', 'transformers'), ('accelerate', 'accelerate'),
    ('bitsandbytes', 'bitsandbytes'), ('safetensors', 'safetensors'),
    ('fastapi', 'fastapi'), ('uvicorn', 'uvicorn'), ('httpx', 'httpx'),
    ('numpy', 'numpy'), ('faiss', 'faiss'), ('pyarrow', 'pyarrow'),
    ('pytest', 'pytest'), ('pytest-asyncio', 'pytest_asyncio'),
]
for label, import_name in packages:
    try:
        mod = importlib.import_module(import_name)
        version = getattr(mod, '__version__', 'unknown')
    except Exception as exc:
        version = f'MISSING ({exc})'
    print(f'{label}={version}', flush=True)
PY

# --- 12. Safeguard: no mutation below /kaggle/input is permitted.
if [[ -d /kaggle/input ]]; then
  if find /kaggle/input -newer "$ROOT/kaggle/bootstrap.sh" -type f 2>/dev/null | grep -q .; then
    echo "ERROR: bootstrap altered files under /kaggle/input" >&2
    exit 5
  fi
fi

echo "bootstrap: OK"
