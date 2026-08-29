# REST API

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](api.vi.md)

The service exposes a small FastAPI surface.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Process liveness |
| GET | `/ready` | Worker/index readiness |
| GET | `/metrics` | Scheduler and worker metrics |
| GET | `/info` | Runtime/model metadata |
| POST | `/v1/embeddings` | Generate embeddings |
| POST | `/v1/search` | Semantic search |

## Embeddings

```json
{
  "model": "qwen3-embedding-8b-kaggle",
  "input": ["hello", "xin chào"],
  "dimensions": 1024,
  "is_query": true
}
```

`dimensions` accepts 32–4096. The public demos exercise 256, 1024 and 4096.

## Search

```json
{
  "query": "nhà khoa học Marie Curie",
  "top_k": 5,
  "language": "vi"
}
```

Search results include rank, similarity score, Wikidata QID and bilingual labels.

## Authentication

Local-only mode does not require public exposure. When optional external exposure is enabled, `API_KEY` is required and protected routes fail closed.

## Limits

Request body, text length, item count, token estimate, queue capacity and sequence length are bounded by `app.config.Settings`.
