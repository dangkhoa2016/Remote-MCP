from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Callable

from dataset.acquire_wikidata import (
    ACTION_API_ENDPOINT,
    DEFAULT_SEEDS,
    WDQS_ENDPOINT,
    AcquisitionResult,
    SeedCategory,
    WikidataClient,
    acquire_wikidata_raw,
)
from dataset.build_wikidata import BuildResult, build_dataset
from dataset.schema import SOURCE, SOURCE_LICENSE


@dataclass(frozen=True, slots=True)
class PublicBuildResult:
    acquisition_result: AcquisitionResult
    build_result: BuildResult
    kaggle_metadata_path: Path
    provenance_metadata_path: Path


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rewrite_checksums(output_dir: Path) -> None:
    checksum_path = output_dir / "SHA256SUMS"
    files = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != checksum_path.name
    )
    lines = [f"{_sha256_file(path)}  {path.name}" for path in files]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_public_dataset(
    *,
    output_dir: Path,
    work_dir: Path,
    target_rows: int,
    user_agent: str,
    seeds: tuple[SeedCategory, ...] = DEFAULT_SEEDS,
    discovery_page_size: int = 250,
    entity_batch_size: int = 50,
    overfetch_factor: float = 1.35,
    min_request_interval: float = 0.35,
    timeout_seconds: float = 60.0,
    max_discovery_factor: float = 2.5,
    client=None,
    parquet_writer: Callable | None = None,
    kaggle_owner: str = "dangkhoa2016",
    kaggle_slug: str = "wikidata-en-vi-semantic-search-100k",
    kaggle_title: str = "Wikidata EN-VI Semantic Search 100K",
) -> PublicBuildResult:
    output_dir = Path(output_dir)
    work_dir = Path(work_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    if client is None:
        client = WikidataClient(
            user_agent,
            min_request_interval=min_request_interval,
            timeout_seconds=timeout_seconds,
        )
    acquisition = acquire_wikidata_raw(
        work_dir,
        target_rows=target_rows,
        client=client,
        seeds=seeds,
        discovery_page_size=discovery_page_size,
        entity_batch_size=entity_batch_size,
        overfetch_factor=overfetch_factor,
        max_discovery_factor=max_discovery_factor,
    )

    build = build_dataset(
        acquisition.raw_entities_path,
        output_dir,
        limit=target_rows,
        parquet_writer=parquet_writer,
    )
    if build.accepted_rows != target_rows:
        raise RuntimeError(
            f"canonical build did not produce exact target: expected {target_rows}, got {build.accepted_rows}"
        )

    published_raw_qids = output_dir / acquisition.raw_qids_path.name
    published_raw_entities = output_dir / acquisition.raw_entities_path.name
    if acquisition.raw_qids_path.resolve() != published_raw_qids.resolve():
        shutil.copyfile(acquisition.raw_qids_path, published_raw_qids)
    if acquisition.raw_entities_path.resolve() != published_raw_entities.resolve():
        shutil.copyfile(acquisition.raw_entities_path, published_raw_entities)

    quality = json.loads(build.quality_report_path.read_text(encoding="utf-8"))
    metadata = {
        "format_version": 1,
        "source": SOURCE,
        "source_license": SOURCE_LICENSE,
        "derived_license": SOURCE_LICENSE,
        "content_policy": "structured_wikidata_only_no_wikipedia_article_bodies",
        "languages": ["en", "vi"],
        "target_rows": target_rows,
        "canonical_rows": build.accepted_rows,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_filename": build.parquet_path.name,
        "canonical_sha256": _sha256_file(build.parquet_path),
        "language_null_rates": quality.get("null_rates", {}),
        "acquisition": {
            "method": "wdqs+wikibase-action-api",
            "wdqs_endpoint": WDQS_ENDPOINT,
            "action_api_endpoint": ACTION_API_ENDPOINT,
            "sequential_requests": True,
            "resume_supported": True,
            "raw_qids_filename": published_raw_qids.name,
            "raw_qids_sha256": _sha256_file(published_raw_qids),
            "raw_entities_filename": published_raw_entities.name,
            "raw_entities_sha256": _sha256_file(published_raw_entities),
            "unique_qids": acquisition.unique_qids,
            "fetched_entities": acquisition.fetched_entities,
            "accepted_before_canonical_limit": acquisition.accepted_rows,
            "discovery_page_size": discovery_page_size,
            "entity_batch_size": entity_batch_size,
            "overfetch_factor": overfetch_factor,
            "min_request_interval_seconds": min_request_interval,
            "max_discovery_factor": max_discovery_factor,
        },
        "seed_categories": [
            {"name": seed.name, "instance_of_qid": seed.instance_of_qid, "weight": seed.weight}
            for seed in seeds
        ],
        "reproducibility_note": (
            "Live Wikidata changes over time. The published raw JSONL files plus SHA256SUMS freeze the exact "
            "acquisition used to reproduce this canonical Parquet artifact."
        ),
    }
    provenance_metadata_path = output_dir / "provenance-metadata.json"
    provenance_metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if not kaggle_owner.strip() or not kaggle_slug.strip() or not kaggle_title.strip():
        raise ValueError("Kaggle owner, slug, and title must be non-empty")
    kaggle_metadata = {
        "title": kaggle_title,
        "id": f"{kaggle_owner.strip()}/{kaggle_slug.strip()}",
        "licenses": [{"name": "CC0-1.0"}],
    }
    kaggle_metadata_path = output_dir / "dataset-metadata.json"
    kaggle_metadata_path.write_text(
        json.dumps(kaggle_metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rewrite_checksums(output_dir)
    return PublicBuildResult(acquisition, build, kaggle_metadata_path, provenance_metadata_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acquire and build the canonical public Wikidata EN/VI CC0 Kaggle dataset"
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--target-rows", type=int, default=100_000)
    parser.add_argument("--user-agent", required=True, help="Descriptive Wikimedia User-Agent with contact info")
    parser.add_argument("--discovery-page-size", type=int, default=250)
    parser.add_argument("--entity-batch-size", type=int, default=50)
    parser.add_argument("--overfetch-factor", type=float, default=1.35)
    parser.add_argument("--min-request-interval", type=float, default=0.35)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--kaggle-owner", default="dangkhoa2016")
    parser.add_argument("--kaggle-slug", default="wikidata-en-vi-semantic-search-100k")
    parser.add_argument("--kaggle-title", default="Wikidata EN-VI Semantic Search 100K")
    parser.add_argument("--max-discovery-factor", type=float, default=2.5)
    args = parser.parse_args()

    result = build_public_dataset(
        output_dir=args.output_dir,
        work_dir=args.work_dir,
        target_rows=args.target_rows,
        user_agent=args.user_agent,
        discovery_page_size=args.discovery_page_size,
        entity_batch_size=args.entity_batch_size,
        overfetch_factor=args.overfetch_factor,
        min_request_interval=args.min_request_interval,
        timeout_seconds=args.timeout_seconds,
        max_discovery_factor=args.max_discovery_factor,
        kaggle_owner=args.kaggle_owner,
        kaggle_slug=args.kaggle_slug,
        kaggle_title=args.kaggle_title,
    )
    print(f"CANONICAL_ROWS={result.build_result.accepted_rows}")
    print(f"PARQUET={result.build_result.parquet_path}")
    print(f"KAGGLE_METADATA={result.kaggle_metadata_path}")
    print(f"PROVENANCE_METADATA={result.provenance_metadata_path}")
    print(f"SHA256SUMS={Path(args.output_dir) / 'SHA256SUMS'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
