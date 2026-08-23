from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.metrics import Metrics
from app.scheduler.scheduler import QueueFullError, ScheduledEmbeddingResult


class FakeScheduler:
    def __init__(self, *, ready=True, queue_full=False, nan_indices=()):
        self.ready = ready
        self.queue_full = queue_full
        self.nan_indices = set(nan_indices)
        self.metrics = Metrics()
        self.calls = []

    async def embed(self, texts, dimensions, is_query):
        self.calls.append((list(texts), dimensions, is_query))
        if self.queue_full:
            raise QueueFullError('full')
        vectors = []
        for i, _ in enumerate(texts):
            if i in self.nan_indices:
                vectors.append([float('nan')] + [0.0] * (dimensions - 1))
            else:
                vectors.append([float(i)] + [0.0] * (dimensions - 1))
        return ScheduledEmbeddingResult(vectors, token_count=sum(len(t.split()) for t in texts))

    def workers_ready(self):
        return self.ready


class FakeSearch:
    async def search(self, query, top_k, language=None):
        return [{'rank': 1, 'score': 0.99, 'qid': 'Q64', 'label_en': 'Berlin', 'label_vi': 'Berlin'}][:top_k]


def make_client(*, ready=True, queue_full=False, search=True, max_items=8, max_body_bytes=2_000_000, max_text_characters=32768, api_key=None, nan_indices=()):
    from app.main import Runtime, create_app

    runtime = Runtime(
        settings=Settings(worker_count=2, max_request_items=max_items, max_request_body_bytes=max_body_bytes, max_text_characters=max_text_characters, api_key=api_key),
        scheduler=FakeScheduler(ready=ready, queue_full=queue_full, nan_indices=nan_indices),
        search_service=FakeSearch() if search else None,
        model_dir=Path('/kaggle/input/qwen-qwen3-embedding-8b/transformers/default/1'),
        model_fingerprint='fp',
        gpu_names=['Tesla T4', 'Tesla T4'],
        index_size=100000 if search else 0,
    )
    return TestClient(create_app(runtime)), runtime


def test_embeddings_openai_shape_preserves_indexes_and_dimensions():
    client, runtime = make_client()
    response = client.post('/v1/embeddings', json={
        'model': 'qwen3-embedding-8b-kaggle',
        'input': ['hello world', 'xin chào'],
        'dimensions': 32,
    })
    assert response.status_code == 200
    body = response.json()
    assert body['object'] == 'list'
    assert [x['index'] for x in body['data']] == [0, 1]
    assert all(len(x['embedding']) == 32 for x in body['data'])
    assert body['usage']['total_tokens'] == 4
    assert runtime.scheduler.calls[0][2] is False


def test_embeddings_rejects_invalid_dimension():
    client, _ = make_client()
    assert client.post('/v1/embeddings', json={'input': ['x'], 'dimensions': 31}).status_code == 422


def test_embeddings_rejects_too_many_items():
    client, _ = make_client(max_items=1)
    response = client.post('/v1/embeddings', json={'input': ['a', 'b'], 'dimensions': 32})
    assert response.status_code == 413


def test_queue_full_maps_to_retryable_429():
    client, _ = make_client(queue_full=True)
    response = client.post('/v1/embeddings', json={'input': ['a'], 'dimensions': 32})
    assert response.status_code == 429
    assert response.json()['detail']['retryable'] is True


def test_health_is_live_when_ready_is_false():
    client, _ = make_client(ready=False)
    assert client.get('/health').status_code == 200
    ready = client.get('/ready')
    assert ready.status_code == 503
    assert ready.json()['detail']['status'] == 'not_ready'


def test_info_proves_kaggle_input_model_source():
    client, _ = make_client()
    body = client.get('/info').json()
    assert body['model_source'] == 'kaggle_input'
    assert body['worker_count'] == 2
    assert body['gpu_names'] == ['Tesla T4', 'Tesla T4']


def test_search_returns_structured_hit_and_uses_query_semantics():
    client, _ = make_client(search=True)
    response = client.post('/v1/search', json={'query': 'thủ đô của Đức', 'top_k': 5, 'language': 'vi'})
    assert response.status_code == 200
    assert response.json()['data'][0]['qid'] == 'Q64'


def test_post_request_body_is_bounded_before_endpoint_processing():
    client, runtime = make_client(max_body_bytes=128)
    response = client.post('/v1/embeddings', json={
        'input': ['x' * 512],
        'dimensions': 32,
    })
    assert response.status_code == 413
    assert response.json()['detail']['error'] == 'request_body_too_large'
    assert runtime.scheduler.calls == []


def test_auth_protects_every_non_health_operational_route():
    client, _ = make_client(api_key='secret')
    assert client.get('/health').status_code == 200
    assert client.get('/health').json() == {'status': 'ok'}
    assert client.get('/ready').status_code == 401
    assert client.get('/metrics').status_code == 401
    assert client.get('/info').status_code == 401
    assert client.post('/v1/embeddings', json={'input': ['x'], 'dimensions': 32}).status_code == 401
    assert client.post('/v1/search', json={'query': 'Berlin'}).status_code == 401


def test_auth_valid_key_allows_protected_operational_routes():
    client, _ = make_client(api_key='secret')
    headers = {'Authorization': 'Bearer secret'}
    assert client.get('/ready', headers=headers).status_code == 200
    assert client.get('/metrics', headers=headers).status_code == 200
    assert client.get('/info', headers=headers).status_code == 200


def test_auth_wrong_key_is_rejected():
    client, _ = make_client(api_key='secret')
    assert client.get('/info', headers={'Authorization': 'Bearer wrong'}).status_code == 401



def test_whitespace_only_input_is_rejected_before_scheduler():
    client, runtime = make_client()
    response = client.post('/v1/embeddings', json={'input': ['  \n\t  '], 'dimensions': 32})
    assert response.status_code == 422
    assert runtime.scheduler.calls == []


def test_embeddings_rejects_both_dimension_boundaries_outside_contract():
    client, runtime = make_client()
    for dimension in (31, 4097):
        response = client.post('/v1/embeddings', json={'input': ['x'], 'dimensions': dimension})
        assert response.status_code == 422
    assert runtime.scheduler.calls == []


def test_too_long_text_is_rejected_before_scheduler():
    client, runtime = make_client(max_text_characters=8)
    response = client.post('/v1/embeddings', json={'input': ['123456789'], 'dimensions': 32})
    assert response.status_code == 413
    assert runtime.scheduler.calls == []


def test_duplicate_inputs_preserve_response_order_and_cardinality():
    client, runtime = make_client()
    payload = ['same', 'different', 'same']
    response = client.post('/v1/embeddings', json={'input': payload, 'dimensions': 32})
    assert response.status_code == 200
    body = response.json()
    assert [item['index'] for item in body['data']] == [0, 1, 2]
    assert [item['embedding'][0] for item in body['data']] == [0.0, 1.0, 2.0]
    assert runtime.scheduler.calls[0][0] == payload


def test_queue_full_response_has_retry_after_header():
    client, _ = make_client(queue_full=True)
    response = client.post('/v1/embeddings', json={'input': ['a'], 'dimensions': 32})
    assert response.status_code == 429
    assert response.headers['retry-after'] == '1'


def test_malformed_bearer_scheme_is_rejected_before_scheduler():
    client, runtime = make_client(api_key='secret')
    response = client.post(
        '/v1/embeddings',
        headers={'Authorization': 'Basic secret'},
        json={'input': ['x'], 'dimensions': 32},
    )
    assert response.status_code == 401
    assert runtime.scheduler.calls == []


def test_non_finite_embedding_returns_deterministic_422_not_json_crash():
    client, runtime = make_client(nan_indices=(1,))
    response = client.post(
        '/v1/embeddings',
        json={'input': ['hello', 'code snippet'], 'dimensions': 32},
    )
    assert response.status_code == 422
    detail = response.json()['detail']
    assert detail == {
        "error": "embedding_not_finite",
        "indices": [1],
        "count": 1,
    }
    assert 'samples' not in detail
    assert 'code snippet' not in response.text


def test_non_finite_embedding_422_does_not_echo_input_samples():
    client, _ = make_client(nan_indices=(1,))
    response = client.post(
        "/v1/embeddings",
        json={"input": ["hello", "private user text"], "dimensions": 32},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail == {
        "error": "embedding_not_finite",
        "indices": [1],
        "count": 1,
    }
    assert "private user text" not in response.text
    assert "samples" not in detail


def test_all_finite_embeddings_are_unaffected_by_nan_guard():
    client, _ = make_client()
    response = client.post(
        '/v1/embeddings',
        json={'input': ['hello', 'xin chào'], 'dimensions': 32},
    )
    assert response.status_code == 200
    assert [x['index'] for x in response.json()['data']] == [0, 1]
