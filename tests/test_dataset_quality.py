def test_english_suspicion_is_transparent_and_conservative():
    from app.qualification.dataset_quality import suspected_english_in_vi
    assert suspected_english_in_vi('capital city of the German state') is True
    assert suspected_english_in_vi('thủ đô của bang ở Đức') is False
    assert suspected_english_in_vi(None) is False


def test_dataset_quality_reports_nulls_identical_and_suspected_english():
    from app.qualification.dataset_quality import summarize_dataset_quality
    rows = [
        {'label_en': 'Berlin', 'label_vi': 'Berlin', 'description_en': 'capital city',
         'description_vi': 'capital city of Germany', 'document_en': 'Berlin. capital city',
         'document_vi': 'Berlin. capital city of Germany', 'instance_of_qids': ['Q515']},
        {'label_en': 'Hanoi', 'label_vi': 'Hà Nội', 'description_en': None,
         'description_vi': 'thủ đô Việt Nam', 'document_en': None,
         'document_vi': 'Hà Nội. thủ đô Việt Nam', 'instance_of_qids': ['Q515']},
    ]
    out = summarize_dataset_quality(rows)
    assert out['row_count'] == 2
    assert out['suspected_english_vi']['description_vi']['count'] == 1
    assert out['null_rates']['document_en'] == 0.5
    assert out['identical_en_vi']['label']['count'] == 1
    assert out['category_coverage']['Q515']['rows'] == 2
