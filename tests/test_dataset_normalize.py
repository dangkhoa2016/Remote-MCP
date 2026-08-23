import importlib


def _n():
    return importlib.import_module('dataset.normalize')


def test_canonical_record_builds_structured_cc0_documents():
    n = _n()
    raw = {
        'qid': 'Q64',
        'label_en': ' Berlin ',
        'label_vi': 'Berlin',
        'description_en': 'capital and largest city of Germany',
        'description_vi': 'thủ đô và thành phố lớn nhất của Đức',
        'aliases_en': ['Berlin', 'Berlin', 'City of Berlin'],
        'aliases_vi': ['Béc-lin'],
        'instance_of_qids': ['Q515'],
    }
    record = n.canonicalize_record(raw)
    assert isinstance(record, n.CanonicalRecord)
    assert record.qid == 'Q64'
    assert record.source == 'wikidata'
    assert record.source_license == 'CC0-1.0'
    assert record.aliases_en == ['Berlin', 'City of Berlin']
    assert record.document_en.startswith('Berlin. capital and largest city of Germany.')
    assert 'Aliases: Berlin; City of Berlin.' in record.document_en
    assert record.document_vi.startswith('Berlin. thủ đô và thành phố lớn nhất của Đức.')


def test_record_with_no_usable_label_is_rejected():
    n = _n()
    record = n.canonicalize_record({'qid': 'Q1', 'label_en': ' ', 'label_vi': None})
    assert isinstance(record, n.RejectedRecord)
    assert record.reason == 'missing_usable_label'


def test_mojibake_flag_is_aggregated_without_deleting_text():
    n = _n()
    record = n.canonicalize_record({
        'qid': 'Q2',
        'label_en': 'FranÃ§ois',
        'description_en': 'example',
        'aliases_en': [],
    })
    assert isinstance(record, n.CanonicalRecord)
    assert record.label_en == 'FranÃ§ois'
    assert 'suspicious_mojibake' in record.quality_flags


def test_invalid_unicode_record_is_rejected_not_partially_written():
    n = _n()
    record = n.canonicalize_record({
        'qid': 'Q3',
        'label_en': 'bad\ufffdname',
        'description_en': 'example',
    })
    assert isinstance(record, n.RejectedRecord)
    assert record.reason.startswith('unicode_quality:')
