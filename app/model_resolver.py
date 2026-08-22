from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json


class ModelResolutionError(RuntimeError):
    pass


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _has_tokenizer_files(path: Path) -> bool:
    if not (path / "tokenizer_config.json").is_file():
        return False
    return any((path / name).is_file() for name in ("tokenizer.json", "tokenizer.model", "vocab.json"))


def _weight_files(path: Path) -> list[Path]:
    single = path / "model.safetensors"
    if single.is_file():
        return [single]
    index = path / "model.safetensors.index.json"
    if not index.is_file():
        return []
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
        names = sorted(set(data.get("weight_map", {}).values()))
    except (OSError, json.JSONDecodeError, AttributeError):
        return []
    shards = [path / name for name in names]
    return [index, *shards] if names and all(p.is_file() for p in shards) else []


def validate_model_dir(path: Path) -> None:
    path = path.resolve()
    if not path.is_dir():
        raise ModelResolutionError(f"Model directory does not exist: {path}")
    if not (path / "config.json").is_file():
        raise ModelResolutionError(f"Model directory is missing config.json: {path}")
    if not _has_tokenizer_files(path):
        raise ModelResolutionError(f"Model directory is missing tokenizer files: {path}")
    if not _weight_files(path):
        raise ModelResolutionError(f"Model directory is missing valid safetensors weights: {path}")


def _candidate_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    candidates: set[Path] = set()
    # Kaggle model attachments are shallow, but cap traversal to avoid scanning arbitrary trees.
    for config in root.rglob("config.json"):
        try:
            rel = config.relative_to(root)
        except ValueError:
            continue
        if len(rel.parts) > 8:
            continue
        parent = config.parent.resolve()
        try:
            validate_model_dir(parent)
        except ModelResolutionError:
            continue
        candidates.add(parent)
    return sorted(candidates)


def resolve_kaggle_model_dir(root: Path, explicit: str | None) -> Path:
    root = root.resolve()
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not _is_under(path, root):
            raise ModelResolutionError(f"KAGGLE_MODEL_DIR must resolve under {root}; got {path}")
        validate_model_dir(path)
        return path

    candidates = _candidate_dirs(root)
    preferred = [p for p in candidates if "qwen-qwen3-embedding-8b" in str(p).lower()]
    selected = preferred if preferred else candidates
    if not selected:
        raise ModelResolutionError(
            "No valid Qwen3-Embedding-8B Kaggle Model input found. Attach "
            "dangkhoa2016/qwen-qwen3-embedding-8b via Add Input → Models, or set KAGGLE_MODEL_DIR."
        )
    if len(selected) > 1:
        joined = "\n  - ".join(str(p) for p in selected)
        raise ModelResolutionError(
            "Multiple valid model directories found; set KAGGLE_MODEL_DIR explicitly:\n  - " + joined
        )
    return selected[0]


def model_fingerprint(path: Path) -> str:
    path = path.resolve()
    validate_model_dir(path)
    interesting = [path / "config.json", path / "tokenizer_config.json", *_weight_files(path)]
    digest = sha256()
    for file in sorted(set(interesting)):
        stat = file.stat()
        digest.update(file.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
        if file.name.endswith(".json"):
            digest.update(file.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()
