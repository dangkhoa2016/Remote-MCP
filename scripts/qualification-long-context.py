#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from time import perf_counter

from app.config import Settings, enforce_offline_environment
from app.inference.protocol import EmbedWork
from app.inference.worker import WorkerProcessClient, WorkerRemoteError
from app.model_resolver import resolve_kaggle_model_dir
from app.qualification.long_context import TARGETS, materialize_final_results, next_targets_after_results


def _token_count(tokenizer, text: str) -> int:
    return len(tokenizer(text, add_special_tokens=True, truncation=False)['input_ids'])


def _text_for_target(tokenizer, target: int) -> tuple[str, int]:
    unit = 'semantic retrieval multilingual embedding benchmark with Vietnamese and English context. '
    text = unit * max(1, target // 8)
    encoded = tokenizer(text, add_special_tokens=True, truncation=False)['input_ids']
    if len(encoded) > target:
        text = tokenizer.decode(encoded[: max(1, target - 8)], skip_special_tokens=True)
    count = _token_count(tokenizer, text)
    while count < target - 64:
        text += unit
        count = _token_count(tokenizer, text)
    while count > target:
        text = text[: max(1, int(len(text) * target / count) - 1)]
        count = _token_count(tokenizer, text)
    if not (target - 64 <= count <= target):
        raise RuntimeError(f'could not construct deterministic text near target {target}; got {count}')
    return text, count


async def _run_one(model_dir: Path, target: int, text: str) -> dict:
    settings = Settings(
        model_dir=str(model_dir),
        worker_count=1,
        max_sequence_tokens=target,
        max_batch_items=1,
        max_batch_estimated_tokens=target,
    )
    client = WorkerProcessClient(0, model_dir, settings, physical_gpu_id=0)
    started = perf_counter()
    try:
        client.start(timeout=300)
        result = await client.submit(EmbedWork(f'long-context-{target}', [0], [text], 1024, False))
        elapsed = perf_counter() - started
        memory = result.cuda_memory
        return {
            'target_tokens': target,
            'actual_tokens': result.token_count,
            'latency_seconds': round(elapsed, 6),
            'status': 'PASS',
            'cuda_max_allocated_bytes': memory.max_allocated_bytes if memory else None,
            'cuda_max_reserved_bytes': memory.max_reserved_bytes if memory else None,
        }
    except WorkerRemoteError as exc:
        message = str(exc)
        status = 'OOM' if ('OutOfMemoryError' in message or 'out of memory' in message.lower()) else 'ERROR'
        return {
            'target_tokens': target,
            'actual_tokens': None,
            'latency_seconds': round(perf_counter() - started, 6),
            'status': status,
            'error': message,
        }
    except Exception as exc:
        return {
            'target_tokens': target,
            'actual_tokens': None,
            'latency_seconds': round(perf_counter() - started, 6),
            'status': 'ERROR',
            'error': f'{type(exc).__name__}: {exc}',
        }
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description='Isolated Qwen3 long-context T4 envelope probe')
    parser.add_argument('--input-root', type=Path, default=Path(os.environ.get('KAGGLE_INPUT_ROOT', '/kaggle/input')))
    parser.add_argument('--model-dir', default=os.environ.get('KAGGLE_MODEL_DIR'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--continue-after-oom', action='store_true')
    args = parser.parse_args()

    enforce_offline_environment()
    model_dir = resolve_kaggle_model_dir(args.input_root, args.model_dir)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=False)

    results: list[dict] = []
    for target in TARGETS:
        text, constructed_tokens = _text_for_target(tokenizer, target)
        result = asyncio.run(_run_one(model_dir, target, text))
        result['constructed_token_count'] = constructed_tokens
        results.append(result)
        if result['status'] != 'PASS' and not args.continue_after_oom:
            break

    report = {
        'schema_version': 1,
        'targets': list(TARGETS),
        'normal_service_max_sequence_tokens': Settings().max_sequence_tokens,
        'results': materialize_final_results(TARGETS, results),
        'executed_targets': [int(r['target_tokens']) for r in results],
        'remaining_targets': list(next_targets_after_results(results)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if results and results[0]['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
