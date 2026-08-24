from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from time import perf_counter
import json

from app.qualification.evidence import sha256_json, workload_fingerprint

import httpx
import numpy as np

SAMPLE_TEXTS = [
    'Berlin is the capital of Germany.',
    'Berlin là thủ đô của Đức.',
    'Semantic search finds meaning rather than exact keywords.',
    'Tìm kiếm ngữ nghĩa tìm nội dung theo ý nghĩa thay vì từ khóa chính xác.',
]


def summarize(latencies: list[float], *, elapsed: float, total_requests: int, total_items: int, concurrency: int, label: str, workload: dict | None = None, errors: int = 0) -> dict:
    if not latencies or elapsed <= 0:
        raise ValueError('latencies must be non-empty and elapsed must be positive')
    values = np.asarray(latencies, dtype=np.float64) * 1000.0
    workload = dict(workload or {})
    return {
        'worker_mode': label,
        'errors': int(errors),
        'workload': workload,
        'workload_fingerprint': workload_fingerprint(workload),
        'concurrency': concurrency,
        'total_requests': total_requests,
        'total_items': total_items,
        'elapsed_seconds': round(elapsed, 6),
        'requests_per_second': round(total_requests / elapsed, 6),
        'throughput_items_per_second': round(total_items / elapsed, 6),
        'latency_ms': {
            'min': round(float(values.min()), 3),
            'p50': round(float(np.percentile(values, 50)), 3),
            'p95': round(float(np.percentile(values, 95)), 3),
            'p99': round(float(np.percentile(values, 99)), 3),
            'max': round(float(values.max()), 3),
        },
    }


async def run_benchmark(url: str, *, requests: int, concurrency: int, items_per_request: int, dimensions: int, label: str, api_key: str | None = None) -> dict:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
    timeout = httpx.Timeout(300.0)
    errors = 0
    error_lock = asyncio.Lock()
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        async def one(request_id: int) -> None:
            nonlocal errors
            texts = [SAMPLE_TEXTS[(request_id * items_per_request + i) % len(SAMPLE_TEXTS)] for i in range(items_per_request)]
            async with semaphore:
                started = perf_counter()
                try:
                    response = await client.post(
                        f"{url.rstrip('/')}/v1/embeddings",
                        json={'model': 'qwen3-embedding-8b-kaggle', 'input': texts, 'dimensions': dimensions},
                    )
                    response.raise_for_status()
                    body = response.json()
                    if len(body.get('data', [])) != items_per_request:
                        raise RuntimeError('embedding API returned the wrong number of items')
                except Exception:
                    async with error_lock:
                        errors += 1
                finally:
                    latencies.append(perf_counter() - started)
        started_all = perf_counter()
        await asyncio.gather(*(one(i) for i in range(requests)))
        elapsed = perf_counter() - started_all
    workload = {
        'requests': requests,
        'concurrency': concurrency,
        'items_per_request': items_per_request,
        'dimensions': dimensions,
        'sample_text_sha256': sha256_json(SAMPLE_TEXTS),
    }
    return summarize(
        latencies,
        elapsed=elapsed,
        total_requests=requests,
        total_items=requests * items_per_request,
        concurrency=concurrency,
        label=label,
        workload=workload,
        errors=errors,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Benchmark the Qwen3 embedding REST API')
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--requests', type=int, default=20)
    parser.add_argument('--concurrency', type=int, default=4)
    parser.add_argument('--items-per-request', type=int, default=8)
    parser.add_argument('--dimensions', type=int, default=1024)
    parser.add_argument('--label', default='benchmark')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--api-key', default=None)
    args = parser.parse_args()
    result = asyncio.run(run_benchmark(
        args.url,
        requests=args.requests,
        concurrency=args.concurrency,
        items_per_request=args.items_per_request,
        dimensions=args.dimensions,
        label=args.label,
        api_key=args.api_key,
    ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get('errors', 0) else 0


if __name__ == '__main__':
    raise SystemExit(main())
