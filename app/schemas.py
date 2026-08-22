from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class EmbeddingRequest(BaseModel):
    model: str = "qwen3-embedding-8b-kaggle"
    input: str | list[str]
    dimensions: int = Field(default=4096, ge=32, le=4096)
    is_query: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)
    language: Literal["en", "vi"] | None = None
