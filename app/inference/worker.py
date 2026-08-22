from __future__ import annotations

import asyncio
import os
import queue
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from app.config import Settings
from app.inference.protocol import EmbedResult, EmbedWork, WorkerFailure, WorkerReady


class WorkerRemoteError(RuntimeError):
    pass


_STOP = "__STOP__"


def _default_factory(worker_id: int, model_dir: Path, settings: Settings):
    # Import model code only inside the child after CUDA_VISIBLE_DEVICES is set.
    from app.inference.model import LocalQwenEmbedder

    return LocalQwenEmbedder(model_dir, "cuda:0", settings)


def _worker_main(
    worker_id: int,
    physical_gpu_id: int,
    model_dir: str,
    settings: Settings,
    command_queue,
    result_queue,
    embedder_factory,
) -> None:
    os.environ["CUDA_VISIBLE_DEVICES"] = str(physical_gpu_id)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
    try:
        factory = embedder_factory or _default_factory
        embedder = factory(worker_id, Path(model_dir), settings)
        if embedder_factory is None:
            # Real worker: prove model execution before readiness.
            embedder.encode(["warmup"], 32, False)
            import torch
            gpu_name = torch.cuda.get_device_name(0)
        else:
            gpu_name = f"fake-gpu-{worker_id}"
        result_queue.put(WorkerReady(worker_id=worker_id, gpu_name=gpu_name))
    except BaseException as exc:
        result_queue.put(WorkerFailure(worker_id=worker_id, request_id=None, error=f"startup: {type(exc).__name__}: {exc}"))
        return

    while True:
        message = command_queue.get()
        if message == _STOP:
            return
        if not isinstance(message, EmbedWork):
            result_queue.put(WorkerFailure(worker_id, None, f"invalid worker message: {type(message).__name__}"))
            continue
        try:
            output = embedder.encode(message.texts, message.dimensions, message.is_query)
            result_queue.put(
                EmbedResult(
                    request_id=message.request_id,
                    item_indexes=message.item_indexes,
                    embeddings=output.embeddings,
                    token_count=output.token_count,
                    cuda_memory=output.cuda_memory,
                )
            )
        except BaseException as exc:
            result_queue.put(
                WorkerFailure(
                    worker_id=worker_id,
                    request_id=message.request_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )


class WorkerProcessClient:
    def __init__(
        self,
        worker_id: int,
        model_dir: Path,
        settings: Settings,
        *,
        embedder_factory: Any = None,
        physical_gpu_id: int | None = None,
    ) -> None:
        self.worker_id = worker_id
        self.model_dir = Path(model_dir)
        self.settings = settings
        self.embedder_factory = embedder_factory
        self.physical_gpu_id = worker_id if physical_gpu_id is None else physical_gpu_id
        self._ctx = get_context("spawn")
        self._commands = self._ctx.Queue()
        self._results = self._ctx.Queue()
        self._process = None
        self._ready = False
        self._gpu_name: str | None = None
        self._submit_lock: asyncio.Lock | None = None

    @property
    def gpu_name(self) -> str | None:
        return self._gpu_name

    def start(self, timeout: float = 120.0) -> None:
        if self._process is not None and self._process.is_alive():
            return
        self._process = self._ctx.Process(
            target=_worker_main,
            args=(
                self.worker_id,
                self.physical_gpu_id,
                str(self.model_dir),
                self.settings,
                self._commands,
                self._results,
                self.embedder_factory,
            ),
            daemon=True,
        )
        self._process.start()
        try:
            message = self._results.get(timeout=timeout)
        except queue.Empty as exc:
            self.close()
            raise RuntimeError(f"worker {self.worker_id} readiness timed out") from exc
        if isinstance(message, WorkerFailure):
            self.close()
            raise WorkerRemoteError(message.error)
        if not isinstance(message, WorkerReady):
            self.close()
            raise RuntimeError(f"worker {self.worker_id} returned invalid readiness message")
        self._ready = True
        self._gpu_name = message.gpu_name

    def is_alive(self) -> bool:
        return bool(self._process is not None and self._process.is_alive())

    def is_ready(self) -> bool:
        return self._ready and self.is_alive()

    async def submit(self, work: EmbedWork) -> EmbedResult:
        if not self.is_ready():
            raise RuntimeError(f"worker {self.worker_id} is not ready")
        if self._submit_lock is None:
            self._submit_lock = asyncio.Lock()
        async with self._submit_lock:
            await asyncio.to_thread(self._commands.put, work)
            message = await asyncio.to_thread(self._results.get)
            if isinstance(message, WorkerFailure):
                self._ready = False
                raise WorkerRemoteError(message.error)
            if not isinstance(message, EmbedResult):
                self._ready = False
                raise WorkerRemoteError(f"unexpected result from worker {self.worker_id}: {type(message).__name__}")
            if message.request_id != work.request_id:
                self._ready = False
                raise WorkerRemoteError(
                    f"request id mismatch from worker {self.worker_id}: expected {work.request_id}, got {message.request_id}"
                )
            return message

    def close(self, timeout: float = 5.0) -> None:
        self._ready = False
        process = self._process
        if process is None:
            return
        if process.is_alive():
            try:
                self._commands.put(_STOP)
            except Exception:
                pass
            process.join(timeout=timeout)
        if process.is_alive():
            process.terminate()
            process.join(timeout=timeout)
        self._process = None
