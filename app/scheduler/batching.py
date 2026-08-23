from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class BatchItem:
    index: int
    text: str
    estimated_tokens: int


def estimate_tokens(text: str) -> int:
    # Admission/scheduling estimate only. API token usage comes from the real tokenizer.
    return max(1, ceil(len(text) / 4))


def projected_padding_cost(items: Sequence[BatchItem]) -> int:
    if not items:
        return 0
    max_tokens = max(max(1, item.estimated_tokens) for item in items)
    return len(items) * max_tokens


def batch_item_cost(items: Sequence[BatchItem]) -> int:
    return projected_padding_cost(items)


def split_micro_batches(
    items: Iterable[BatchItem], *, max_items: int, max_estimated_tokens: int
) -> list[list[BatchItem]]:
    if max_items < 1 or max_estimated_tokens < 1:
        raise ValueError("batch limits must be positive")
    batches: list[list[BatchItem]] = []
    current: list[BatchItem] = []
    for item in items:
        candidate = [*current, item]
        would_overflow = bool(current) and (
            len(candidate) > max_items
            or projected_padding_cost(candidate) > max_estimated_tokens
        )
        if would_overflow:
            batches.append(current)
            current = []
            candidate = [item]
        current = candidate
        if len(current) >= max_items or projected_padding_cost(current) >= max_estimated_tokens:
            batches.append(current)
            current = []
    if current:
        batches.append(current)
    return batches
