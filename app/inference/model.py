from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import torch
import torch.nn.functional as F

from app.config import Settings, enforce_offline_environment
from app.inference.protocol import CudaMemoryStats


def last_token_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    # If every row ends in a valid token, left padding (or no padding) makes the last token correct.
    if bool(torch.all(attention_mask[:, -1] == 1)):
        return last_hidden_state[:, -1]
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_state.shape[0]
    return last_hidden_state[torch.arange(batch_size, device=last_hidden_state.device), sequence_lengths]


def normalize_and_truncate(embeddings: torch.Tensor, dimensions: int, *, max_dimensions: int = 4096) -> torch.Tensor:
    if not 32 <= int(dimensions) <= int(max_dimensions):
        raise ValueError(f"dimensions must be between 32 and {max_dimensions}")
    sliced = embeddings[:, :dimensions]
    return F.normalize(sliced, p=2, dim=1)


def prepare_texts(texts: Sequence[str], *, is_query: bool, query_instruction: str) -> list[str]:
    return [query_instruction + text if is_query else text for text in texts]


@dataclass(frozen=True, slots=True)
class EncodeOutput:
    embeddings: list[list[float]]
    token_count: int
    cuda_memory: CudaMemoryStats | None = None


class LocalQwenEmbedder:
    def __init__(self, model_dir: Path, device: str, settings: Settings):
        enforce_offline_environment()
        from transformers import AutoModel, AutoTokenizer, BitsAndBytesConfig

        self.settings = settings
        self.device = device
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(model_dir), local_files_only=True, trust_remote_code=False, padding_side="left"
        )
        self.tokenizer.padding_side = "left"
        quant = BitsAndBytesConfig(load_in_8bit=True)
        self.model = AutoModel.from_pretrained(
            str(model_dir),
            local_files_only=True,
            trust_remote_code=False,
            quantization_config=quant,
            device_map={"": device},
            torch_dtype=torch.float16,
        )
        self.model.eval()
        self.max_dimensions = int(getattr(self.model.config, "hidden_size", 4096))

    @torch.inference_mode()
    def encode(self, texts: Sequence[str], dimensions: int, is_query: bool) -> EncodeOutput:
        if self.device.startswith("cuda"):
            torch.cuda.reset_peak_memory_stats()
        prepared = prepare_texts(texts, is_query=is_query, query_instruction=self.settings.query_instruction)
        batch = self.tokenizer(
            prepared,
            padding=True,
            truncation=True,
            max_length=min(
                self.settings.max_sequence_tokens,
                int(getattr(self.model.config, "max_position_embeddings", self.settings.max_sequence_tokens)),
            ),
            return_tensors="pt",
        )
        token_count = int(batch["attention_mask"].sum().item())
        batch = {k: v.to(self.device) for k, v in batch.items()}
        outputs = self.model(**batch)
        pooled = last_token_pool(outputs.last_hidden_state, batch["attention_mask"])
        normalized = normalize_and_truncate(pooled, dimensions, max_dimensions=self.max_dimensions)
        stats = None
        if self.device.startswith("cuda"):
            stats = CudaMemoryStats(
                max_allocated_bytes=int(torch.cuda.max_memory_allocated()),
                max_reserved_bytes=int(torch.cuda.max_memory_reserved()),
            )
        return EncodeOutput(
            embeddings=normalized.float().cpu().tolist(),
            token_count=token_count,
            cuda_memory=stats,
        )
