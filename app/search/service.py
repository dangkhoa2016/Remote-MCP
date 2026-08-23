from __future__ import annotations

import numpy as np

from app.search.index import VectorIndex


class SearchService:
    def __init__(self, scheduler, index: VectorIndex):
        self.scheduler = scheduler
        self.index = index

    async def search(self, query: str, top_k: int, language: str | None = None) -> list[dict]:
        result = await self.scheduler.embed([query], self.index.metadata.dimensions, True)
        hits = self.index.search(np.asarray(result.embeddings[0], dtype=np.float32), top_k)
        payload = []
        for rank, hit in enumerate(hits, 1):
            row = dict(hit.row)
            payload.append({"rank": rank, "score": hit.score, **row})
        return payload
