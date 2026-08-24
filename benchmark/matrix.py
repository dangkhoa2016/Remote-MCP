from __future__ import annotations

from dataclasses import asdict, dataclass
from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class MatrixCase:
    id: str
    worker_count: int
    concurrency: int
    items_per_request: int
    dimensions: int
    requests: int

    @property
    def per_worker_concurrency(self) -> float:
        return self.concurrency / self.worker_count


DEFAULT_MATRIX = (
    MatrixCase('s1-c1-i1-d1024', 1, 1, 1, 1024, 16),
    MatrixCase('s1-c2-i8-d1024', 1, 2, 8, 1024, 16),
    MatrixCase('s1-c4-i16-d1024', 1, 4, 16, 1024, 16),
    MatrixCase('s1-c2-i8-d4096', 1, 2, 8, 4096, 12),
    MatrixCase('s1-c4-i4-d4096', 1, 4, 4, 4096, 12),
    MatrixCase('d2-c2-i1-d1024', 2, 2, 1, 1024, 16),
    MatrixCase('d2-c4-i8-d1024', 2, 4, 8, 1024, 16),
    MatrixCase('d2-c8-i8-d1024', 2, 8, 8, 1024, 24),
    MatrixCase('d2-c8-i16-d1024', 2, 8, 16, 1024, 16),
    MatrixCase('d2-c4-i8-d4096', 2, 4, 8, 4096, 12),
    MatrixCase('d2-c8-i4-d4096', 2, 8, 4, 4096, 12),
    MatrixCase('d2-c16-i4-d1024', 2, 16, 4, 1024, 24),
)


def default_matrix() -> tuple[MatrixCase, ...]:
    return DEFAULT_MATRIX


def _stable(result: dict) -> bool:
    return int(result.get('errors', 0)) == 0 and int(result.get('rejected_429', 0)) == 0


def _best(results: list[dict], workers: int) -> dict | None:
    candidates = [r for r in results if int(r.get('worker_count', 0)) == workers and _stable(r)]
    if not candidates:
        return None
    return max(candidates, key=lambda r: float(r.get('throughput_items_per_second', 0.0)))


def _shape_key(result: dict) -> tuple:
    workers = max(1, int(result['worker_count']))
    return (
        int(result['items_per_request']),
        int(result['dimensions']),
        int(result['requests']),
        float(result['concurrency']) / workers,
    )


def summarize_matrix(results: Sequence[dict]) -> dict:
    raw = [dict(item) for item in results]
    matched_scaling: list[dict] = []
    singles = [r for r in raw if int(r.get('worker_count', 0)) == 1 and _stable(r)]
    duals = [r for r in raw if int(r.get('worker_count', 0)) == 2 and _stable(r)]
    for single in singles:
        for dual in duals:
            if _shape_key(single) != _shape_key(dual):
                continue
            single_tput = float(single.get('throughput_items_per_second', 0.0))
            dual_tput = float(dual.get('throughput_items_per_second', 0.0))
            if single_tput <= 0:
                continue
            matched_scaling.append({
                'single_case_id': single.get('case_id'),
                'dual_case_id': dual.get('case_id'),
                'items_per_request': int(single['items_per_request']),
                'dimensions': int(single['dimensions']),
                'requests': int(single['requests']),
                'per_worker_concurrency': float(single['concurrency']),
                'throughput_ratio': round(dual_tput / single_tput, 6),
                'single_workload_fingerprint': single.get('workload_fingerprint'),
                'dual_workload_fingerprint': dual.get('workload_fingerprint'),
            })

    flattening: list[dict] = []
    groups: dict[tuple, list[dict]] = {}
    for result in raw:
        if not _stable(result):
            continue
        key = (int(result['worker_count']), int(result['items_per_request']), int(result['dimensions']))
        groups.setdefault(key, []).append(result)
    for group in groups.values():
        ordered = sorted(group, key=lambda r: int(r['concurrency']))
        for lower, higher in zip(ordered, ordered[1:]):
            low_t = float(lower.get('throughput_items_per_second', 0.0))
            high_t = float(higher.get('throughput_items_per_second', 0.0))
            low_p95 = float(lower.get('latency_ms', {}).get('p95', 0.0))
            high_p95 = float(higher.get('latency_ms', {}).get('p95', 0.0))
            gain = ((high_t - low_t) / low_t) if low_t > 0 else 0.0
            if gain < 0.05 and high_p95 > low_p95:
                flattening.append({
                    'lower_case_id': lower.get('case_id'),
                    'higher_case_id': higher.get('case_id'),
                    'throughput_gain_fraction': round(gain, 6),
                    'p95_latency_increase_ms': round(high_p95 - low_p95, 3),
                })

    return {
        'matrix_schema_version': 1,
        'best_stable_single': _best(raw, 1),
        'best_stable_dual': _best(raw, 2),
        'matched_scaling': matched_scaling,
        'flattening': flattening,
        'raw_cases': raw,
    }
