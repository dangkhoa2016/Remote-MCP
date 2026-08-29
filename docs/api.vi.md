# REST API

> 🌐 Language / Ngôn ngữ: [English](api.md) | **Tiếng Việt**

Service cung cấp một FastAPI surface nhỏ và rõ ràng.

## Endpoint

| Method | Path | Mục đích |
|---|---|---|
| GET | `/health` | Liveness của process |
| GET | `/ready` | Readiness của worker/index |
| GET | `/metrics` | Metrics của scheduler và worker |
| GET | `/info` | Metadata runtime/model |
| POST | `/v1/embeddings` | Tạo embedding |
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

`dimensions` nhận giá trị 32–4096. Public demo dùng 256, 1024 và 4096.

## Search

```json
{
  "query": "nhà khoa học Marie Curie",
  "top_k": 5,
  "language": "vi"
}
```

Kết quả search gồm rank, similarity score, Wikidata QID và label song ngữ.

## Authentication

Local-only mode không cần public exposure. Khi bật external exposure tùy chọn, `API_KEY` là bắt buộc và protected routes fail-closed.

## Giới hạn

Request body, text length, item count, token estimate, queue capacity và sequence length được giới hạn bởi `app.config.Settings`.
