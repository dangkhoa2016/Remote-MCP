from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
import json
import math
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.config import Settings, enforce_offline_environment
from app.inference.worker import WorkerProcessClient
from app.model_resolver import model_fingerprint, resolve_kaggle_model_dir
from app.scheduler.scheduler import EmbeddingScheduler, QueueFullError
from app.schemas import EmbeddingRequest, SearchRequest
from app.security import AuthError, authorize_bearer
from app.search.index import IndexMetadata, VectorIndex
from app.search.service import SearchService
from app.unicode_quality import UnicodeQualityError, normalize_text


class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = int(max_bytes)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                if int(raw_length) > self.max_bytes:
                    response = JSONResponse(
                        status_code=413,
                        content={"detail": {"error": "request_body_too_large"}},
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            response = JSONResponse(
                status_code=413,
                content={"detail": {"error": "request_body_too_large"}},
            )
            await response(scope, receive, send)


@dataclass
class Runtime:
    settings: Settings
    scheduler: Any
    search_service: Any | None
    model_dir: Path
    model_fingerprint: str
    gpu_names: list[str]
    index_size: int = 0
    workers: list[Any] | None = None

    def close(self) -> None:
        for worker in self.workers or []:
            try:
                worker.close()
            except Exception:
                pass


def _load_search_service(settings: Settings, scheduler, fingerprint: str):
    index_dir_value = os.getenv("SEARCH_INDEX_DIR")
    if not index_dir_value:
        return None, 0
    index_dir = Path(index_dir_value)
    meta_data = json.loads((index_dir / "index-metadata.json").read_text(encoding="utf-8"))
    expected = IndexMetadata(
        model_fingerprint=fingerprint,
        dimensions=settings.embedding_dimensions,
        row_count=int(meta_data["row_count"]),
        dataset_sha256=str(meta_data["dataset_sha256"]),
    )
    index = VectorIndex.load(index_dir, expected_metadata=expected)
    return SearchService(scheduler, index), index.metadata.row_count


def build_runtime(settings: Settings | None = None) -> Runtime:
    enforce_offline_environment()
    settings = settings or Settings.from_env()
    model_dir = resolve_kaggle_model_dir(settings.kaggle_input_root, settings.model_dir)
    fingerprint = model_fingerprint(model_dir)
    workers = [
        WorkerProcessClient(i, model_dir, settings, physical_gpu_id=i)
        for i in range(settings.worker_count)
    ]
    started: list[WorkerProcessClient] = []
    try:
        for worker in workers:
            worker.start()
            started.append(worker)
        scheduler = EmbeddingScheduler(workers, settings)
        search_service, index_size = _load_search_service(settings, scheduler, fingerprint)
        return Runtime(
            settings=settings,
            scheduler=scheduler,
            search_service=search_service,
            model_dir=model_dir,
            model_fingerprint=fingerprint,
            gpu_names=[worker.gpu_name or f"gpu-{worker.worker_id}" for worker in workers],
            index_size=index_size,
            workers=workers,
        )
    except Exception:
        for worker in started:
            worker.close()
        raise


def _validate_api_texts(texts: list[str], settings: Settings) -> list[str]:
    if not texts:
        raise HTTPException(status_code=422, detail={"error": "input must contain at least one text"})
    if len(texts) > settings.max_request_items:
        raise HTTPException(status_code=413, detail={"error": "too many input items"})
    cleaned: list[str] = []
    for text in texts:
        if len(text) > settings.max_text_characters:
            raise HTTPException(status_code=413, detail={"error": "input text exceeds character limit"})
        try:
            normalized = normalize_text(text).text
        except UnicodeQualityError as exc:
            raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc
        if not normalized:
            raise HTTPException(status_code=422, detail={"error": "input text must not be empty"})
        cleaned.append(normalized)
    return cleaned


def _non_finite_embedding_indices(embeddings: list[list[float]]) -> list[int]:
    found: list[int] = []
    for index, vector in enumerate(embeddings):
        if not all(
            isinstance(value, (int, float)) and math.isfinite(float(value))
            for value in vector
        ):
            found.append(index)
    return found


def create_app(runtime: Runtime | None = None) -> FastAPI:
    injected = runtime is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not injected:
            app.state.runtime = build_runtime()
        try:
            yield
        finally:
            if not injected and getattr(app.state, "runtime", None) is not None:
                app.state.runtime.close()

    app = FastAPI(title="Qwen3-Embedding-8B T4x2 Kaggle API", version=__version__, lifespan=lifespan)
    body_limit = runtime.settings.max_request_body_bytes if runtime is not None else int(os.getenv("MAX_REQUEST_BODY_BYTES", "2000000"))
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=body_limit)
    if runtime is not None:
        app.state.runtime = runtime

    def rt(request: Request) -> Runtime:
        current = getattr(request.app.state, "runtime", None)
        if current is None:
            raise HTTPException(status_code=503, detail={"status": "not_ready"})
        return current

    def require_auth(request: Request, current: Runtime, authorization: str | None) -> None:
        try:
            authorize_bearer(
                path=request.url.path,
                authorization=authorization,
                api_key=current.settings.api_key,
            )
        except AuthError as exc:
            raise HTTPException(status_code=401, detail={"error": "unauthorized"}) from exc

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(request: Request, authorization: str | None = Header(default=None)):
        current = rt(request)
        require_auth(request, current, authorization)
        if not current.scheduler.workers_ready():
            raise HTTPException(status_code=503, detail={"status": "not_ready"})
        return {"status": "ready", "workers": current.settings.worker_count, "search_enabled": current.search_service is not None}

    @app.get("/metrics")
    async def metrics(request: Request, authorization: str | None = Header(default=None)):
        current = rt(request)
        require_auth(request, current, authorization)
        return current.scheduler.metrics.snapshot()

    @app.get("/info")
    async def info(request: Request, authorization: str | None = Header(default=None)):
        current = rt(request)
        require_auth(request, current, authorization)
        return {
            "version": __version__,
            "model": "qwen3-embedding-8b-kaggle",
            "model_source": "kaggle_input",
            "resolved_model_path": str(current.model_dir),
            "model_fingerprint": current.model_fingerprint,
            "precision": "int8",
            "worker_count": current.settings.worker_count,
            "gpu_names": current.gpu_names,
            "embedding_dimensions": current.settings.embedding_dimensions,
            "dataset_source": "wikidata",
            "dataset_license": "CC0-1.0",
            "index_size": current.index_size,
        }

    @app.post("/v1/embeddings")
    async def embeddings(payload: EmbeddingRequest, request: Request, authorization: str | None = Header(default=None)):
        current = rt(request)
        require_auth(request, current, authorization)
        texts = [payload.input] if isinstance(payload.input, str) else list(payload.input)
        texts = _validate_api_texts(texts, current.settings)
        try:
            result = await current.scheduler.embed(texts, payload.dimensions, payload.is_query)
        except QueueFullError as exc:
            raise HTTPException(
                status_code=429,
                detail={"error": "queue_full", "retryable": True, "message": str(exc)},
                headers={"Retry-After": "1"},
            ) from exc
        non_finite = _non_finite_embedding_indices(result.embeddings)
        if non_finite:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "embedding_not_finite",
                    "indices": list(non_finite),
                    "count": len(non_finite),
                },
            )
        data = [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(result.embeddings)
        ]
        return {
            "object": "list",
            "data": data,
            "model": "qwen3-embedding-8b-kaggle",
            "usage": {"prompt_tokens": result.token_count, "total_tokens": result.token_count},
        }

    @app.post("/v1/search")
    async def search(payload: SearchRequest, request: Request, authorization: str | None = Header(default=None)):
        current = rt(request)
        require_auth(request, current, authorization)
        if current.search_service is None:
            raise HTTPException(status_code=503, detail={"error": "search_index_not_loaded"})
        query = _validate_api_texts([payload.query], current.settings)[0]
        data = await current.search_service.search(query, payload.top_k, payload.language)
        return {"object": "search_result", "data": data}

    return app


app = create_app()
