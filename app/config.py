from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def enforce_offline_environment() -> None:
    """Force Hugging Face ecosystem libraries into local-files-only mode."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")


@dataclass(frozen=True, slots=True)
class Settings:
    kaggle_input_root: Path = Path("/kaggle/input")
    working_dir: Path = Path("/kaggle/working/qwen3-embedding-8b-t4x2")
    model_dir: str | None = None
    worker_count: int = 2
    embedding_dimensions: int = 4096
    max_batch_items: int = 16
    max_batch_estimated_tokens: int = 512
    max_queue_estimated_tokens: int = 32768
    max_request_items: int = 128
    max_request_body_bytes: int = 2_000_000
    max_text_characters: int = 32768
    max_sequence_tokens: int = 4096
    query_instruction: str = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: "
    api_key: str | None = None
    expose_mode: str = "off"

    @classmethod
    def from_env(cls) -> "Settings":
        enforce_offline_environment()
        expose_mode = os.getenv("EXPOSE_MODE", "off").strip() or "off"
        if expose_mode not in {"off", "cloudflare-quick"}:
            raise ValueError("EXPOSE_MODE must be off or cloudflare-quick")
        api_key = os.getenv("API_KEY") or None
        if expose_mode == "cloudflare-quick" and api_key is None:
            raise ValueError("API_KEY is required when EXPOSE_MODE=cloudflare-quick")
        return cls(
            kaggle_input_root=Path(os.getenv("KAGGLE_INPUT_ROOT", "/kaggle/input")),
            working_dir=Path(os.getenv("WORKING_DIR", "/kaggle/working/qwen3-embedding-8b-t4x2")),
            model_dir=os.getenv("KAGGLE_MODEL_DIR") or None,
            worker_count=int(os.getenv("WORKER_COUNT", "2")),
            embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "4096")),
            max_batch_items=int(os.getenv("MAX_BATCH_ITEMS", "16")),
            max_batch_estimated_tokens=int(os.getenv("MAX_BATCH_ESTIMATED_TOKENS", "512")),
            max_queue_estimated_tokens=int(os.getenv("MAX_QUEUE_ESTIMATED_TOKENS", "32768")),
            max_request_items=int(os.getenv("MAX_REQUEST_ITEMS", "128")),
            max_request_body_bytes=int(os.getenv("MAX_REQUEST_BODY_BYTES", "2000000")),
            max_text_characters=int(os.getenv("MAX_TEXT_CHARACTERS", "32768")),
            max_sequence_tokens=int(os.getenv("MAX_SEQUENCE_TOKENS", "4096")),
            query_instruction=os.getenv(
                "QUERY_INSTRUCTION",
                "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: ",
            ),
            api_key=api_key,
            expose_mode=expose_mode,
        )
