#!/usr/bin/env bash
#
# Secret-safe release packaging.
#
# Produces from a clean tree:
#   qwen3-embedding-8b-t4x2-v<v>.zip                 (source, no .git/)
#   qwen3-embedding-8b-t4x2-v<v>-with-git.zip        (includes .git/, no evidence/secrets/caches)
#   qwen3-embedding-8b-t4x2-v<v>-evidence.tar.gz     (sanitized qualification evidence only)
#   qwen3-embedding-8b-t4x2-v<v>-artifacts.sha256    (checksum manifest)
#
# Every artifact is passed through scripts/scan-release-artifact.py before the
# checksum manifest is accepted. No raw API key, Authorization header,
# trycloudflare hostname, secret file, or cache member may be present.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

VERSION="${VERSION:-1.0.0}"
OUT_DIR="${OUT_DIR:-$ROOT/dist}"
EVIDENCE_DIRS=()
for arg in "$@"; do
  case "$arg" in
    --version=*) VERSION="${arg#--version=}" ;;
    --out=*) OUT_DIR="${arg#--out=}" ;;
    --evidence=*) EVIDENCE_DIRS+=("${arg#--evidence=}") ;;
    *) echo "ERROR: unknown argument: $arg" >&2; exit 2 ;;
  esac
done

SCANNER="$ROOT/scripts/scan-release-artifact.py"
[[ -x "$SCANNER" || -f "$SCANNER" ]] || { echo "ERROR: scanner missing: $SCANNER" >&2; exit 2; }

mkdir -p "$OUT_DIR"
SOURCE_COMMIT_COUNT="$(git rev-list --count HEAD)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

BASE="qwen3-embedding-8b-t4x2-v${VERSION}"
SRC_ZIP="$OUT_DIR/$BASE.zip"
GIT_ZIP="$OUT_DIR/$BASE-with-git.zip"
EVI_TGZ="$OUT_DIR/$BASE-evidence.tar.gz"
SHA="$OUT_DIR/$BASE-artifacts.sha256"

echo "== source zip (no .git) =="
git archive --format=zip -o "$SRC_ZIP" HEAD

echo "== with-git zip (clone-based, remote/tag-stripped) =="
GIT_STAGE="$STAGE/with-git"
git clone --no-hardlinks --no-tags "$ROOT" "$GIT_STAGE"
git -C "$GIT_STAGE" remote remove origin || true

# Remove anything remote-derived that must not survive packaging.
rm -rf "$GIT_STAGE/.git/refs/remotes"
rm -rf "$GIT_STAGE/.git/logs/refs/remotes"
rm -f  "$GIT_STAGE/.git/FETCH_HEAD"

# Archive contract forbids tags.
mapfile -t local_tags < <(git -C "$GIT_STAGE" tag -l)
if [[ ${#local_tags[@]} -gt 0 ]]; then
  git -C "$GIT_STAGE" tag -d "${local_tags[@]}"
fi

[[ -z "$(git -C "$GIT_STAGE" remote)" ]]
[[ -z "$(git -C "$GIT_STAGE" tag -l)" ]]
[[ -z "$(git -C "$GIT_STAGE" status --porcelain)" ]]
[[ "$(git -C "$GIT_STAGE" rev-list --count HEAD)" == "$SOURCE_COMMIT_COUNT" ]]

git -C "$GIT_STAGE" fsck --full
! test -e "$GIT_STAGE/.git/refs/remotes/origin/HEAD"
! find "$GIT_STAGE/.git/logs/refs/remotes" -type f -print -quit 2>/dev/null | grep -q .
(cd "$GIT_STAGE" && zip -rq "$GIT_ZIP" .)

echo "== evidence archive (sanitized) =="
if [[ ${#EVIDENCE_DIRS[@]} -gt 0 ]]; then
  EVI_STAGE="$STAGE/evidence"
  mkdir -p "$EVI_STAGE"
  for dir in "${EVIDENCE_DIRS[@]}"; do
    [[ -d "$dir" ]] || { echo "ERROR: evidence dir missing: $dir" >&2; exit 2; }
    cp -R "$dir" "$EVI_STAGE/$(basename "$dir")"
  done
  # Remove anything that must never be archived, even from evidence.
  find "$EVI_STAGE" \( \
      -name 'api-key' -o -name 'api_key' -o \
      -name '*.trycloudflare.com' -o \
      -path '*/.pytest_cache/*' -o -path '*/__pycache__/*' -o -name '*.pyc' \
      -o -path '*/secrets/*' \) -prune -exec rm -rf {} +
  (cd "$EVI_STAGE" && tar -czf "$EVI_TGZ" .)
else
  echo "  (no --evidence= dir supplied; emitting empty evidence archive)"
  tar -czf "$EVI_TGZ" --files-from /dev/null
fi

echo "== secret scan of every artifact =="
for artifact in "$SRC_ZIP" "$GIT_ZIP" "$EVI_TGZ"; do
  python "$SCANNER" "$artifact"
done

echo "== checksum manifest (portable basenames) =="
(
  cd "$OUT_DIR"
  sha256sum \
    "$(basename "$SRC_ZIP")" \
    "$(basename "$GIT_ZIP")" \
    "$(basename "$EVI_TGZ")" \
    > "$(basename "$SHA")"

  sha256sum -c "$(basename "$SHA")"
)

echo "== produced =="
ls -l "$SRC_ZIP" "$GIT_ZIP" "$EVI_TGZ" "$SHA"
