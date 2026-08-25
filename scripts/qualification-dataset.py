#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.dataset_resolver import resolve_kaggle_dataset_dir, validate_dataset_dir
from app.qualification.dataset_quality import summarize_dataset_quality


def main() -> int:
    parser = argparse.ArgumentParser(description='Measure EN/VI coverage and purity signals for the canonical dataset')
    parser.add_argument('--input-root', type=Path, default=Path(os.environ.get('KAGGLE_INPUT_ROOT', '/kaggle/input')))
    parser.add_argument('--dataset-dir', default=os.environ.get('KAGGLE_DATASET_DIR'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    dataset_dir = resolve_kaggle_dataset_dir(args.input_root, args.dataset_dir)
    manifest = validate_dataset_dir(dataset_dir)
    canonical = dataset_dir / str(manifest['canonical_filename'])

    import pyarrow.parquet as pq
    columns = ['label_en', 'label_vi', 'description_en', 'description_vi', 'document_en', 'document_vi', 'instance_of_qids']
    table = pq.read_table(canonical, columns=columns)
    rows = table.to_pylist()
    report = summarize_dataset_quality(rows)
    report['dataset_dir'] = str(dataset_dir)
    report['canonical_filename'] = str(manifest['canonical_filename'])
    report['canonical_sha256'] = str(manifest['canonical_sha256'])
    report['source'] = str(manifest.get('source'))
    report['source_license'] = str(manifest.get('source_license'))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'row_count': report['row_count'], 'canonical_sha256': report['canonical_sha256']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
