from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
from typing import Callable, Iterable

from dataset.normalize import canonicalize_record
from dataset.schema import CanonicalRecord, RejectedRecord, SOURCE, SOURCE_LICENSE

CANONICAL_FILENAME = "wikidata-en-vi-100k.parquet"


@dataclass(frozen=True, slots=True)
class BuildResult:
    accepted_rows: int
    rejected_rows: int
    output_dir: Path
    parquet_path: Path
    manifest_path: Path
    quality_report_path: Path


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_records(path: Path) -> Iterable[dict]:
    # Python's UTF-8 decoder is strict by default; malformed bytes abort the build.
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        if not isinstance(data, list):
            raise ValueError("JSON input must contain an array of Wikidata records")
        for row in data:
            if not isinstance(row, dict):
                raise ValueError("each JSON record must be an object")
            yield row
        return

    with path.open("r", encoding="utf-8", errors="strict") as fh:
        for line_number, line in enumerate(fh, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"line {line_number}: record must be a JSON object")
            yield row


def _write_parquet(records: list[dict], path: Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "pyarrow is required to write the canonical Parquet dataset; install requirements-kaggle.txt"
        ) from exc
    table = pa.Table.from_pylist(records)
    pq.write_table(table, path, compression="zstd")


def _null_rates(records: list[dict]) -> dict[str, float]:
    if not records:
        return {}
    keys = (
        "label_en",
        "label_vi",
        "description_en",
        "description_vi",
        "document_en",
        "document_vi",
    )
    return {
        key: sum(1 for row in records if row.get(key) is None) / len(records)
        for key in keys
    }


def build_dataset(
    input_path: Path,
    output_dir: Path,
    *,
    limit: int | None = None,
    parquet_writer: Callable[[list[dict], Path], None] | None = None,
) -> BuildResult:
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    accepted: list[dict] = []
    rejected_by_reason: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()
    scanned = 0

    for raw in _read_records(input_path):
        scanned += 1
        normalized = canonicalize_record(raw)
        if isinstance(normalized, RejectedRecord):
            rejected_by_reason[normalized.reason] += 1
            continue
        assert isinstance(normalized, CanonicalRecord)
        row = normalized.to_dict()
        accepted.append(row)
        flag_counts.update(row["quality_flags"])
        if limit is not None and len(accepted) >= limit:
            break

    # Stable order gives reproducible content for the same input selection.
    accepted.sort(key=lambda row: (row.get("qid") or "", row.get("label_en") or "", row.get("label_vi") or ""))

    parquet_path = output_dir / CANONICAL_FILENAME
    writer = parquet_writer or _write_parquet
    writer(accepted, parquet_path)
    parquet_sha = _sha256_file(parquet_path)

    quality = {
        "scanned_rows": scanned,
        "accepted_rows": len(accepted),
        "rejected_rows": sum(rejected_by_reason.values()),
        "rejected_by_reason": dict(sorted(rejected_by_reason.items())),
        "flag_counts": dict(sorted(flag_counts.items())),
        "null_rates": _null_rates(accepted),
    }
    quality_path = output_dir / "data-quality-report.json"
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "format_version": 1,
        "source": SOURCE,
        "source_license": SOURCE_LICENSE,
        "derived_license": SOURCE_LICENSE,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_filename": input_path.name,
        "input_sha256": _sha256_file(input_path),
        "canonical_filename": CANONICAL_FILENAME,
        "canonical_sha256": parquet_sha,
        "row_count": len(accepted),
        "rejected_row_count": sum(rejected_by_reason.values()),
        "languages": ["en", "vi"],
        "content_policy": "structured_wikidata_only",
        "null_rates": quality["null_rates"],
    }
    manifest_path = output_dir / "dataset-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    license_target = output_dir / "LICENSE-DATA.md"
    license_source = Path(__file__).with_name("LICENSE-DATA.md")
    license_target.write_text(license_source.read_text(encoding="utf-8"), encoding="utf-8")

    checksum_targets = [parquet_path, manifest_path, quality_path, license_target]
    checksum_lines = [f"{_sha256_file(path)}  {path.name}" for path in checksum_targets]
    (output_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    return BuildResult(
        accepted_rows=len(accepted),
        rejected_rows=sum(rejected_by_reason.values()),
        output_dir=output_dir,
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        quality_report_path=quality_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the canonical CC0 Wikidata EN/VI semantic-search dataset")
    parser.add_argument("--input", required=True, type=Path, help="Local UTF-8 JSONL or JSON export")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    result = build_dataset(args.input, args.output_dir, limit=args.limit)
    print(f"ACCEPTED_ROWS={result.accepted_rows}")
    print(f"REJECTED_ROWS={result.rejected_rows}")
    print(f"PARQUET={result.parquet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
