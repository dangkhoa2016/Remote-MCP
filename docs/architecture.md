# Architecture

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](architecture.vi.md)

## Runtime topology

The application is a CPU-side FastAPI gateway plus two persistent embedding workers, one worker bound to each Kaggle Tesla T4.

```text
read-only Kaggle Inputs
  ├─ Qwen3-Embedding-8B model
  └─ canonical dataset / verified index
                ↓
         FastAPI gateway
                ↓
      bounded token scheduler
          ↙           ↘
     cuda:0 worker  cuda:1 worker
          ↘           ↙
       normalized embeddings
                ↓
      semantic-search index
```

The model is not tensor-sharded. Each worker owns an independent model replica.

## Offline-first model path

The model resolver accepts only paths under `/kaggle/input`. Hugging Face ecosystem offline flags are enabled and model loading uses local files.

## Scheduler

The scheduler bounds requests by item count, estimated tokens, sequence length, queue cost, and worker readiness. It preserves input ordering and reports per-worker metrics.

## Search

The canonical index stores normalized corpus vectors aligned with bilingual Wikidata rows. Search compares normalized vectors and returns QID plus English/Vietnamese labels.

## Security boundary

The normal Kaggle path is local-only. Optional external exposure requires authentication and is explicitly opt-in.

## Mutable state

Read-only inputs remain under `/kaggle/input`; indexes, logs and evidence are written below `/kaggle/working`.
