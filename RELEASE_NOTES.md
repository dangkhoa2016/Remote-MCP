# Release Notes — v1.0.0

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](RELEASE_NOTES.vi.md)

## First public release

v1.0.0 packages the dual-T4 Qwen3-Embedding-8B runtime, bilingual Wikidata semantic search, reproducible Kaggle workflows, qualification tooling, and guided public Quick Demo.

### Highlights

- Qwen3-Embedding-8B loaded from attached Kaggle Model input.
- Two persistent T4 workers with bounded scheduling.
- FastAPI embedding/search endpoints.
- Verified English/Vietnamese Wikidata 100K corpus.
- English, Vietnamese and cross-lingual retrieval.
- Instruction-aware embeddings and flexible dimensions.
- Quick Demo plus full production acceptance and qualification notebooks.
- MIT-licensed source and bilingual public documentation.

### Evidence policy

GPU acceptance is always bound to the exact source revision used by the Kaggle run. Executable changes require a new appropriate runtime run before the new revision claims exact-SHA acceptance.

### License

Copyright (c) 2026 Đăng Khoa <i.am@dangkhoa.dev>. MIT License.
