from pathlib import Path

import pytest

from app.config import Settings
from app.inference.protocol import EmbedWork


class FakeEmbedder:
    def __init__(self, worker_id: int):
        self.worker_id = worker_id

    def encode(self, texts, dimensions, is_query):
        from app.inference.model import EncodeOutput
        vectors = [[float(self.worker_id)] + [0.0] * (dimensions - 1) for _ in texts]
        return EncodeOutput(vectors, token_count=len(texts))


class FakeFactory:
    def __call__(self, worker_id: int, model_dir: Path, settings: Settings):
        return FakeEmbedder(worker_id)


class RaisingEmbedder(FakeEmbedder):
    def encode(self, texts, dimensions, is_query):
        raise RuntimeError('boom')


class RaisingFactory:
    def __call__(self, worker_id: int, model_dir: Path, settings: Settings):
        return RaisingEmbedder(worker_id)


@pytest.mark.asyncio
async def test_spawned_worker_reports_ready_and_routes_result(tmp_path: Path):
    from app.inference.worker import WorkerProcessClient

    client = WorkerProcessClient(0, tmp_path, Settings(worker_count=1), embedder_factory=FakeFactory())
    try:
        client.start(timeout=10)
        assert client.is_alive()
        assert client.is_ready()
        result = await client.submit(EmbedWork('r1', [3], ['hello'], 32, False))
        assert result.request_id == 'r1'
        assert result.item_indexes == [3]
        assert len(result.embeddings[0]) == 32
        assert result.embeddings[0][0] == 0.0
    finally:
        client.close()
    assert not client.is_alive()


@pytest.mark.asyncio
async def test_spawned_worker_failure_is_propagated(tmp_path: Path):
    from app.inference.worker import WorkerProcessClient, WorkerRemoteError

    client = WorkerProcessClient(0, tmp_path, Settings(worker_count=1), embedder_factory=RaisingFactory())
    try:
        client.start(timeout=10)
        with pytest.raises(WorkerRemoteError, match='boom'):
            await client.submit(EmbedWork('r2', [0], ['hello'], 32, False))
        assert client.is_ready() is False
    finally:
        client.close()


def test_spawned_worker_process_death_immediately_clears_readiness(tmp_path: Path):
    from app.inference.worker import WorkerProcessClient

    client = WorkerProcessClient(0, tmp_path, Settings(worker_count=1), embedder_factory=FakeFactory())
    client.start(timeout=10)
    process = client._process
    assert process is not None and process.is_alive()
    process.terminate()
    process.join(timeout=5)
    assert client.is_alive() is False
    assert client.is_ready() is False
    client.close()
    assert client.is_alive() is False
