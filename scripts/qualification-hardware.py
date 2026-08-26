#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark.matrix import summarize_matrix


def _load_results(path: Path) -> list[dict]:
    if path.is_file():
        if path.suffix == '.jsonl':
            return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        payload = json.loads(path.read_text(encoding='utf-8'))
        return payload if isinstance(payload, list) else list(payload.get('results', []))
    results = []
    for file in sorted(path.glob('*.json')):
        payload = json.loads(file.read_text(encoding='utf-8'))
        if isinstance(payload, dict) and 'case_id' in payload:
            results.append(payload)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description='Summarize curated T4x2 benchmark case evidence')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = _load_results(args.input)
    if not results:
        raise SystemExit('no hardware benchmark results found')
    summary = summarize_matrix(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({
        'cases': len(results),
        'best_stable_single': summary['best_stable_single'] and summary['best_stable_single'].get('case_id'),
        'best_stable_dual': summary['best_stable_dual'] and summary['best_stable_dual'].get('case_id'),
        'matched_scaling_pairs': len(summary['matched_scaling']),
        'flattening_events': len(summary['flattening']),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
