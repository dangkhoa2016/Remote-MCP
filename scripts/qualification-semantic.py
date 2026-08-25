#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import httpx

from app.qualification.semantic import evaluate_cases, load_suite


def main() -> int:
    parser = argparse.ArgumentParser(description='Run frozen semantic golden-suite qualification')
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--index-dir', type=Path, required=True)
    parser.add_argument('--suite', type=Path, default=Path('fixtures/semantic-golden/suite-v1.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--api-key-file', type=Path)
    args = parser.parse_args()

    cases = load_suite(args.suite)
    rows = json.loads((args.index_dir / 'rows.json').read_text(encoding='utf-8'))
    available_qids = {str(row['qid']) for row in rows if row.get('qid')}
    headers = {}
    if args.api_key_file:
        key = args.api_key_file.read_text(encoding='utf-8').strip()
        if key:
            headers['Authorization'] = f'Bearer {key}'

    rankings: dict[str, list[str]] = {}
    responses: dict[str, list[dict]] = {}
    with httpx.Client(timeout=120.0, headers=headers) as client:
        for case in cases:
            response = client.post(
                f"{args.url.rstrip('/')}/v1/search",
                json={'query': case.query, 'top_k': case.top_k, 'language': case.language},
            )
            response.raise_for_status()
            body = response.json()
            hits = list(body.get('data', []))
            responses[case.id] = hits
            rankings[case.id] = [str(hit.get('qid')) for hit in hits if hit.get('qid')]

    report = evaluate_cases(cases, available_qids, rankings)
    report['suite_path'] = str(args.suite)
    report['suite_sha256'] = sha256(args.suite.read_bytes()).hexdigest()
    for record in report['cases']:
        record['hits'] = responses.get(record['id'], [])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('total_cases','dataset_covered_cases','hit_at_1','hit_at_5','hit_at_10','mrr')}, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
