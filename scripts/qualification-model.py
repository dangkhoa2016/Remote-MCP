#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import httpx
import numpy as np

from app.qualification.evidence import workload_fingerprint
from app.qualification.model_capabilities import MRL_DIMENSIONS, code_hit_at_k, rank_vectors, topk_overlap
from app.qualification.semantic import evaluate_cases, load_suite
from app.search.index import IndexMetadata, VectorIndex

CROSS_LINGUAL_PAIRS = (
    ('capital-germany', 'current capital of Germany', 'thủ đô hiện nay của Đức'),
    ('capital-france', 'capital of France', 'thủ đô của Pháp'),
    ('python-language', 'Python programming language', 'ngôn ngữ lập trình Python'),
    ('computer-science', 'computer science', 'khoa học máy tính'),
)


def _file_sha(path: Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def _api_key(path: Path | None) -> str | None:
    if not path:
        return None
    value = path.read_text(encoding='utf-8').strip()
    return value or None


def _embed(client: httpx.Client, url: str, texts: list[str], dimensions: int, is_query: bool) -> np.ndarray:
    response = client.post(
        f"{url.rstrip('/')}/v1/embeddings",
        json={
            'model': 'qwen3-embedding-8b-kaggle',
            'input': texts,
            'dimensions': dimensions,
            'is_query': is_query,
        },
    )
    response.raise_for_status()
    body = response.json()
    vectors = [item['embedding'] for item in sorted(body['data'], key=lambda x: x['index'])]
    return np.asarray(vectors, dtype=np.float32)


def _embed_single(client: httpx.Client, url: str, text: str, dimensions: int, is_query: bool) -> list[float] | None:
    """Embed one text; return None when the service reports a measured non-finite (NaN/Inf) embedding."""
    response = client.post(
        f"{url.rstrip('/')}/v1/embeddings",
        json={
            'model': 'qwen3-embedding-8b-kaggle',
            'input': [text],
            'dimensions': dimensions,
            'is_query': is_query,
        },
    )
    if response.status_code == 422:
        detail = response.json().get('detail')
        if isinstance(detail, dict) and detail.get('error') == 'embedding_not_finite':
            return None
    response.raise_for_status()
    body = response.json()
    return body['data'][0]['embedding']


def _rank_queries(index: VectorIndex, query_vectors: np.ndarray, cases) -> dict[str, list[str]]:
    rankings: dict[str, list[str]] = {}
    for case, vector in zip(cases, query_vectors, strict=True):
        rankings[case.id] = [hit.row.get('qid') for hit in index.search(vector, case.top_k) if hit.row.get('qid')]
    return rankings


def main() -> int:
    parser = argparse.ArgumentParser(description='Qualify Qwen3 MRL, instruction, cross-lingual and code-retrieval capabilities')
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--index-dir', type=Path, required=True)
    parser.add_argument('--semantic-suite', type=Path, default=Path('fixtures/semantic-golden/suite-v1.json'))
    parser.add_argument('--code-snippets', type=Path, default=Path('fixtures/code-retrieval/snippets-v1.json'))
    parser.add_argument('--code-queries', type=Path, default=Path('fixtures/code-retrieval/queries-v1.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--api-key-file', type=Path)
    args = parser.parse_args()

    meta = IndexMetadata(**json.loads((args.index_dir / 'index-metadata.json').read_text(encoding='utf-8')))
    vectors = np.load(args.index_dir / 'vectors.npy')
    rows = json.loads((args.index_dir / 'rows.json').read_text(encoding='utf-8'))
    base_index = VectorIndex.build(vectors, rows, meta)
    cases = load_suite(args.semantic_suite)
    available_qids = {str(row['qid']) for row in rows if row.get('qid')}
    headers = {}
    key = _api_key(args.api_key_file)
    if key:
        headers['Authorization'] = f'Bearer {key}'

    report = {
        'schema_version': 1,
        'semantic_suite_sha256': _file_sha(args.semantic_suite),
        'code_snippets_sha256': _file_sha(args.code_snippets),
        'code_queries_sha256': _file_sha(args.code_queries),
        'model_fingerprint': meta.model_fingerprint,
        'dataset_sha256': meta.dataset_sha256,
        'mrl': {'dimensions': list(MRL_DIMENSIONS), 'results': {}},
        'instruction_ab': {},
        'cross_lingual': {},
        'code_retrieval': {},
    }

    with httpx.Client(timeout=300.0, headers=headers) as client:
        query_texts = [case.query for case in cases]
        for dim in MRL_DIMENSIONS:
            projected = base_index.project(dim)
            query_vectors = _embed(client, args.url, query_texts, dim, True)
            rankings = _rank_queries(projected, query_vectors, cases)
            quality = evaluate_cases(cases, available_qids, rankings)
            vector_norms = np.linalg.norm(query_vectors, axis=1)
            workload = {
                'kind': 'mrl-semantic',
                'dimensions': dim,
                'query_count': len(cases),
                'suite_sha256': report['semantic_suite_sha256'],
            }
            report['mrl']['results'][str(dim)] = {
                'quality': {k: quality[k] for k in ('dataset_covered_cases', 'hit_at_1', 'hit_at_5', 'hit_at_10', 'mrr')},
                'query_vector_norm_min': float(vector_norms.min()),
                'query_vector_norm_max': float(vector_norms.max()),
                'corpus_vector_bytes_estimate': int(len(rows) * dim * 4),
                'workload': workload,
                'workload_fingerprint': workload_fingerprint(workload),
                'rankings': rankings,
            }

        ab_dim = 1024
        ab_index = base_index.project(ab_dim)
        with_instruction = _embed(client, args.url, query_texts, ab_dim, True)
        without_instruction = _embed(client, args.url, query_texts, ab_dim, False)
        rankings_with = _rank_queries(ab_index, with_instruction, cases)
        rankings_without = _rank_queries(ab_index, without_instruction, cases)
        quality_with = evaluate_cases(cases, available_qids, rankings_with)
        quality_without = evaluate_cases(cases, available_qids, rankings_without)
        report['instruction_ab'] = {
            'dimensions': ab_dim,
            'with_instruction': {k: quality_with[k] for k in ('dataset_covered_cases','hit_at_1','hit_at_5','hit_at_10','mrr')},
            'without_instruction': {k: quality_without[k] for k in ('dataset_covered_cases','hit_at_1','hit_at_5','hit_at_10','mrr')},
            'rankings_with_instruction': rankings_with,
            'rankings_without_instruction': rankings_without,
        }

        cross_results = []
        for pair_id, en_query, vi_query in CROSS_LINGUAL_PAIRS:
            pair_vectors = _embed(client, args.url, [en_query, vi_query], ab_dim, True)
            en_rank = [hit.row.get('qid') for hit in ab_index.search(pair_vectors[0], 10) if hit.row.get('qid')]
            vi_rank = [hit.row.get('qid') for hit in ab_index.search(pair_vectors[1], 10) if hit.row.get('qid')]
            cross_results.append({
                'id': pair_id,
                'en_query': en_query,
                'vi_query': vi_query,
                'en_top10': en_rank,
                'vi_top10': vi_rank,
                'top10_overlap': topk_overlap(en_rank, vi_rank, 10),
            })
        report['cross_lingual'] = {
            'dimensions': ab_dim,
            'pairs': cross_results,
            'mean_top10_overlap': float(np.mean([x['top10_overlap'] for x in cross_results])) if cross_results else None,
        }

        snippets_payload = json.loads(args.code_snippets.read_text(encoding='utf-8'))
        queries_payload = json.loads(args.code_queries.read_text(encoding='utf-8'))
        snippets = snippets_payload['snippets']
        code_queries = queries_payload['queries']
        snippet_ids: list[str] = []
        snippet_vectors: list[list[float]] = []
        snippet_limitations: list[str] = []
        for snippet in snippets:
            vector = _embed_single(client, args.url, snippet['text'], ab_dim, False)
            if vector is None:
                snippet_limitations.append(str(snippet['id']))
            else:
                snippet_vectors.append(vector)
                snippet_ids.append(str(snippet['id']))
        snippet_matrix = np.asarray(snippet_vectors, dtype=np.float32)
        query_vectors = _embed(client, args.url, [q['query'] for q in code_queries], ab_dim, True)
        code_rankings: dict[str, list[str]] = {}
        expected: dict[str, set[str]] = {}
        raw_rankings: dict[str, list[dict]] = {}
        for query, vector in zip(code_queries, query_vectors, strict=True):
            ranked = rank_vectors(vector, snippet_matrix, snippet_ids, 10)
            query_id = str(query['id'])
            code_rankings[query_id] = [item_id for item_id, _ in ranked]
            raw_rankings[query_id] = [{'id': item_id, 'score': score} for item_id, score in ranked]
            expected[query_id] = set(map(str, query['expected_ids']))
        report['code_retrieval'] = {
            'dimensions': ab_dim,
            'query_count': len(code_queries),
            'snippet_count_total': len(snippets),
            'snippet_count_finite': len(snippet_ids),
            'snippet_count_measured_limitation': len(snippet_limitations),
            'snippet_measured_limitation_ids': snippet_limitations,
            'measured_limitation': {
                'detail': 'INT8 (bitsandbytes) + fp16 model on T4 produced non-finite (NaN) embeddings for '
                          'the listed document-mode code snippets; their embeddings are intentionally excluded '
                          'from retrieval metrics rather than masked.',
                'excluded_snippet_ids': snippet_limitations,
            },
            'hit_at_1': code_hit_at_k(code_rankings, expected, 1),
            'hit_at_5': code_hit_at_k(code_rankings, expected, 5),
            'hit_at_10': code_hit_at_k(code_rankings, expected, 10),
            'rankings': raw_rankings,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({
        'mrl_dimensions': report['mrl']['dimensions'],
        'instruction_ab': report['instruction_ab'],
        'cross_lingual_mean_top10_overlap': report['cross_lingual']['mean_top10_overlap'],
        'code_hit_at_1': report['code_retrieval']['hit_at_1'],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
