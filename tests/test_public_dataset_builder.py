from pathlib import Path
import json


def test_public_builder_writes_acquisition_metadata_and_canonical_artifacts(tmp_path: Path, monkeypatch):
    from dataset.acquire_wikidata import AcquisitionResult
    import dataset.build_public_wikidata as public_builder

    raw_dir = tmp_path / 'work'
    raw_dir.mkdir()
    raw_entities = raw_dir / 'raw-wikidata-en-vi.jsonl'
    raw_qids = raw_dir / 'raw-qids.jsonl'
    rows = [
        {'qid': 'Q1', 'label_en': 'one', 'label_vi': 'một', 'instance_of_qids': ['Q5']},
        {'qid': 'Q2', 'label_en': 'two', 'instance_of_qids': ['Q5']},
    ]
    raw_entities.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in rows) + '\n', encoding='utf-8')
    raw_qids.write_text('\n'.join(json.dumps({'qid': x['qid'], 'seed_names': ['human']}) for x in rows) + '\n', encoding='utf-8')

    def fake_acquire(*args, **kwargs):
        return AcquisitionResult(
            output_dir=raw_dir,
            raw_qids_path=raw_qids,
            raw_entities_path=raw_entities,
            state_path=raw_dir / 'acquisition-state.json',
            unique_qids=2,
            fetched_entities=2,
            accepted_rows=2,
        )

    def fake_parquet_writer(records, path):
        path.write_bytes(json.dumps(records, ensure_ascii=False, sort_keys=True).encode('utf-8'))

    monkeypatch.setattr(public_builder, 'acquire_wikidata_raw', fake_acquire)
    output = tmp_path / 'dataset'
    result = public_builder.build_public_dataset(
        output_dir=output,
        work_dir=raw_dir,
        target_rows=2,
        user_agent='QwenDatasetBot/0.1 (https://example.test/contact)',
        parquet_writer=fake_parquet_writer,
    )

    assert result.build_result.accepted_rows == 2
    kaggle_metadata = json.loads((output / 'dataset-metadata.json').read_text(encoding='utf-8'))
    assert kaggle_metadata['id'] == 'dangkhoa2016/wikidata-en-vi-semantic-search-100k'
    assert kaggle_metadata['licenses'] == [{'name': 'CC0-1.0'}]
    metadata = json.loads((output / 'provenance-metadata.json').read_text(encoding='utf-8'))
    assert metadata['source'] == 'wikidata'
    assert metadata['source_license'] == 'CC0-1.0'
    assert metadata['target_rows'] == 2
    assert metadata['acquisition']['method'] == 'wdqs+wikibase-action-api'
    assert metadata['acquisition']['raw_qids_sha256']
    assert (output / 'wikidata-en-vi-100k.parquet').is_file()
    assert (output / 'dataset-manifest.json').is_file()
    assert (output / 'data-quality-report.json').is_file()
    checksums = (output / 'SHA256SUMS').read_text(encoding='utf-8')
    assert 'dataset-metadata.json' in checksums
    assert 'provenance-metadata.json' in checksums
