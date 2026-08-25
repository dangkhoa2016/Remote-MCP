from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from collections import defaultdict
from typing import Mapping, Sequence


QUALITY_PASS = 'QUALITY_PASS'
DATASET_COVERAGE_MISSING = 'DATASET_COVERAGE_MISSING'
RETRIEVAL_MISS = 'RETRIEVAL_MISS'


@dataclass(frozen=True, slots=True)
class GoldenCase:
    id: str
    query: str
    language: str
    expected_qids: tuple[str, ...]
    top_k: int
    category: str
    rationale: str = ''


def load_suite(path: Path) -> list[GoldenCase]:
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    cases = []
    seen: set[str] = set()
    for raw in payload.get('cases', []):
        case = GoldenCase(
            id=str(raw['id']),
            query=str(raw['query']),
            language=str(raw['language']),
            expected_qids=tuple(str(q) for q in raw['expected_qids']),
            top_k=int(raw.get('top_k', 10)),
            category=str(raw['category']),
            rationale=str(raw.get('rationale', '')),
        )
        if case.id in seen:
            raise ValueError(f'duplicate golden case id: {case.id}')
        if not case.expected_qids:
            raise ValueError(f'golden case {case.id} has no expected QIDs')
        if case.top_k < 1:
            raise ValueError(f'golden case {case.id} has invalid top_k')
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError('semantic suite contains no cases')
    return cases


def reciprocal_rank(expected: set[str], ranked: list[str]) -> float:
    for rank, qid in enumerate(ranked, 1):
        if qid in expected:
            return 1.0 / rank
    return 0.0


def classify_case(case: GoldenCase, available_qids: set[str], ranked_qids: list[str]) -> str:
    expected = set(case.expected_qids)
    if not expected.intersection(available_qids):
        return DATASET_COVERAGE_MISSING
    if expected.intersection(ranked_qids[:case.top_k]):
        return QUALITY_PASS
    return RETRIEVAL_MISS


def _aggregate(cases: Sequence[GoldenCase], available_qids: set[str], rankings: Mapping[str, list[str]]) -> dict:
    covered = [case for case in cases if set(case.expected_qids).intersection(available_qids)]
    denom = len(covered)
    if not denom:
        return {
            'total_cases': len(cases),
            'dataset_covered_cases': 0,
            'coverage_rate': 0.0,
            'hit_at_1': None,
            'hit_at_5': None,
            'hit_at_10': None,
            'mrr': None,
        }

    def hit_at(k: int) -> float:
        hits = 0
        for case in covered:
            ranked = rankings.get(case.id, [])[:k]
            if set(case.expected_qids).intersection(ranked):
                hits += 1
        return hits / denom

    rr = sum(reciprocal_rank(set(case.expected_qids), rankings.get(case.id, [])[:case.top_k]) for case in covered) / denom
    return {
        'total_cases': len(cases),
        'dataset_covered_cases': denom,
        'coverage_rate': denom / len(cases) if cases else 0.0,
        'hit_at_1': hit_at(1),
        'hit_at_5': hit_at(5),
        'hit_at_10': hit_at(10),
        'mrr': rr,
    }


def evaluate_cases(cases: Sequence[GoldenCase], available_qids: set[str], rankings: Mapping[str, list[str]]) -> dict:
    overall = _aggregate(cases, available_qids, rankings)
    case_records = []
    by_language: dict[str, list[GoldenCase]] = defaultdict(list)
    by_category: dict[str, list[GoldenCase]] = defaultdict(list)
    counts = {QUALITY_PASS: 0, DATASET_COVERAGE_MISSING: 0, RETRIEVAL_MISS: 0}

    for case in cases:
        ranked = list(rankings.get(case.id, []))
        status = classify_case(case, available_qids, ranked)
        counts[status] += 1
        expected = set(case.expected_qids)
        rr = None if status == DATASET_COVERAGE_MISSING else reciprocal_rank(expected, ranked[:case.top_k])
        first_rank = None
        if rr:
            first_rank = int(round(1.0 / rr))
        case_records.append({
            'id': case.id,
            'query': case.query,
            'language': case.language,
            'category': case.category,
            'expected_qids': list(case.expected_qids),
            'top_k': case.top_k,
            'status': status,
            'ranked_qids': ranked,
            'first_relevant_rank': first_rank,
            'reciprocal_rank': rr,
        })
        by_language[case.language].append(case)
        by_category[case.category].append(case)

    return {
        **overall,
        'status_counts': counts,
        'per_language': {key: _aggregate(group, available_qids, rankings) for key, group in sorted(by_language.items())},
        'per_category': {key: _aggregate(group, available_qids, rankings) for key, group in sorted(by_category.items())},
        'cases': case_records,
    }
