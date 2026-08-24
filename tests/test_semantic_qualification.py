def test_case_classifies_dataset_missing_before_retrieval_miss():
    from app.qualification.semantic import GoldenCase, classify_case
    case = GoldenCase('x', 'Berlin', 'en', ('Q64',), 10, 'city')
    assert classify_case(case, {'Q586'}, ['Q586']) == 'DATASET_COVERAGE_MISSING'
    assert classify_case(case, {'Q64', 'Q586'}, ['Q586']) == 'RETRIEVAL_MISS'
    assert classify_case(case, {'Q64'}, ['Q64']) == 'QUALITY_PASS'


def test_metrics_use_covered_cases_as_quality_denominator():
    from app.qualification.semantic import evaluate_cases, GoldenCase
    cases = [
        GoldenCase('a', 'a', 'en', ('Q1',), 10, 'city'),
        GoldenCase('b', 'b', 'vi', ('Q2',), 10, 'city'),
    ]
    report = evaluate_cases(cases, {'Q1'}, {'a': ['Q1'], 'b': []})
    assert report['dataset_covered_cases'] == 1
    assert report['hit_at_1'] == 1.0
    assert report['mrr'] == 1.0


def test_retrieval_miss_counts_against_covered_denominator():
    from app.qualification.semantic import evaluate_cases, GoldenCase
    cases = [
        GoldenCase('a', 'a', 'en', ('Q1',), 10, 'city'),
        GoldenCase('b', 'b', 'en', ('Q2',), 10, 'city'),
    ]
    report = evaluate_cases(cases, {'Q1', 'Q2'}, {'a': ['Q1'], 'b': ['Q9', 'Q2']})
    assert report['hit_at_1'] == 0.5
    assert report['hit_at_5'] == 1.0
    assert report['mrr'] == 0.75


def test_frozen_suite_has_exactly_twenty_predeclared_cases():
    from pathlib import Path
    from app.qualification.semantic import load_suite
    cases = load_suite(Path('fixtures/semantic-golden/suite-v1.json'))
    assert len(cases) == 20
    assert cases[0].id == 'vi-current-capital-germany'
    assert cases[0].expected_qids == ('Q64',)
    assert all(case.top_k == 10 for case in cases)
