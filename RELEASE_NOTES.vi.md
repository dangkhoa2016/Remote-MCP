# Ghi chú phát hành — v1.0.0

> 🌐 Language / Ngôn ngữ: [English](RELEASE_NOTES.md) | **Tiếng Việt**

## Bản phát hành public đầu tiên

v1.0.0 đóng gói runtime Qwen3-Embedding-8B dual-T4, semantic search Wikidata song ngữ, workflow Kaggle có khả năng tái lập, qualification tooling và Quick Demo public có hướng dẫn.

### Điểm nổi bật

- Qwen3-Embedding-8B load từ Kaggle Model input đã attach.
- Hai T4 worker persistent với bounded scheduler.
- FastAPI endpoint cho embedding/search.
- Corpus Wikidata 100K Anh/Việt đã xác minh.
- Retrieval tiếng Anh, tiếng Việt và xuyên ngôn ngữ.
- Instruction-aware embedding và flexible dimensions.
- Quick Demo cùng full production acceptance và qualification notebook.
- Source MIT và tài liệu public song ngữ.

### Chính sách evidence

GPU acceptance luôn bind với đúng source revision được dùng trong Kaggle run. Executable change cần runtime run phù hợp mới trước khi revision mới claim exact-SHA acceptance.

### Giấy phép

Copyright (c) 2026 Đăng Khoa <i.am@dangkhoa.dev>. MIT License.
