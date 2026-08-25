#!/usr/bin/env bash
set -Eeuo pipefail
URL="${1:-http://127.0.0.1:8000}"
AUTH=()
if [[ -n "${API_KEY:-}" ]]; then AUTH=(-H "Authorization: Bearer ${API_KEY}"); fi

curl -fsS "$URL/health"
echo
curl -fsS "${AUTH[@]}" "$URL/ready"
echo
curl -fsS "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-embedding-8b-kaggle","input":["Berlin is the capital of Germany.","Berlin là thủ đô của Đức."],"dimensions":1024}' \
  "$URL/v1/embeddings" | python -c 'import json,sys; d=json.load(sys.stdin); assert len(d["data"])==2; assert len(d["data"][0]["embedding"])==1024; print("EMBEDDING_SMOKE=PASS")'

if [[ "${SMOKE_SEARCH:-1}" == "1" ]]; then
  curl -fsS "${AUTH[@]}" -H 'Content-Type: application/json' \
    -d '{"query":"thủ đô của Đức","top_k":10,"language":"vi"}' \
    "$URL/v1/search" | python -c 'import json,sys; d=json.load(sys.stdin); assert d["data"]; print("SEARCH_SMOKE=PASS top_qid="+str(d["data"][0].get("qid")))'
fi
