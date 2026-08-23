from pathlib import Path
import json


def test_builder_emits_manifest_quality_report_and_checksums(tmp_path: Path):
    from dataset.build_wikidata import build_dataset

    raw = tmp_path / 'raw.jsonl'
    rows = [
        {'qid': 'Q64', 'label_en': 'Berlin', 'label_vi': 'Berlin', 'description_en': 'capital of Germany'},
        {'qid': 'Q2', 'label_en': 'FranÃ§ois', 'description_en': 'example', 'aliases_en': ['x', 'x']},
        {'qid': 'Q3', 'label_en': 'bad\ufffdname', 'description_en': 'bad'},
    ]
    raw.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n', encoding='utf-8')
    out = tmp_path / 'out'

    def fake_parquet_writer(records, path):
        path.write_bytes(json.dumps(records, ensure_ascii=False, sort_keys=True).encode('utf-8'))

    result = build_dataset(raw, out, parquet_writer=fake_parquet_writer)

    assert result.accepted_rows == 2
    assert result.rejected_rows == 1
    assert (out / 'wikidata-en-vi-100k.parquet').is_file()
    manifest = json.loads((out / 'dataset-manifest.json').read_text())
    quality = json.loads((out / 'data-quality-report.json').read_text())
    checksums = (out / 'SHA256SUMS').read_text()
    assert manifest['source'] == 'wikidata'
    assert manifest['source_license'] == 'CC0-1.0'
    assert manifest['row_count'] == 2
    assert quality['rejected_by_reason']
    assert quality['flag_counts']['suspicious_mojibake'] == 1
    assert 'wikidata-en-vi-100k.parquet' in checksums
    assert 'CC0' in (out / 'LICENSE-DATA.md').read_text()
