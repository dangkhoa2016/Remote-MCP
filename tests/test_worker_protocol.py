import importlib
import pickle


def _p():
    return importlib.import_module('app.inference.protocol')


def test_embed_work_is_spawn_pickle_safe():
    p = _p()
    work = p.EmbedWork(request_id='r1', item_indexes=[2, 4], texts=['a', 'b'], dimensions=1024, is_query=True)
    restored = pickle.loads(pickle.dumps(work))
    assert restored == work


def test_embed_result_preserves_indexes_and_usage():
    p = _p()
    result = p.EmbedResult(request_id='r1', item_indexes=[1], embeddings=[[0.1, 0.2]], token_count=7)
    assert result.item_indexes == [1]
    assert result.token_count == 7


def test_embed_result_cuda_memory_round_trips_through_pickle():
    p = _p()
    stats = p.CudaMemoryStats(max_allocated_bytes=123, max_reserved_bytes=456)
    result = p.EmbedResult('r2', [0], [[0.1]], token_count=1, cuda_memory=stats)
    restored = pickle.loads(pickle.dumps(result))
    assert restored == result
    assert restored.cuda_memory == stats


def test_embed_result_cuda_memory_defaults_to_none():
    p = _p()
    result = p.EmbedResult('r3', [0], [[0.2]], token_count=1)
    assert result.cuda_memory is None
