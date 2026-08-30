# Qwen3-Embedding-8B trên Kaggle GPU T4×2

> 🌐 Language / Ngôn ngữ: [English](README.md) | **Tiếng Việt**

[![CI](https://github.com/dangkhoa2016/Qwen3-Embedding-8B-On-T4x2-GPU/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/dangkhoa2016/Qwen3-Embedding-8B-On-T4x2-GPU/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/dangkhoa2016/Qwen3-Embedding-8B-On-T4x2-GPU?display_name=tag&sort=semver)](https://github.com/dangkhoa2016/Qwen3-Embedding-8B-On-T4x2-GPU/releases/tag/v1.0.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10--3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Kaggle](https://img.shields.io/badge/Kaggle-T4%20%C3%972-20BEFF?logo=kaggle&logoColor=white)](https://www.kaggle.com/)
[![Model](https://img.shields.io/badge/Qwen3--Embedding--8B-4096d-6C63FF)](https://huggingface.co/Qwen/Qwen3-Embedding-8B)

Dự án **Qwen3-Embedding-8B** có khả năng tái lập cho semantic search và embedding service trên Kaggle **NVIDIA Tesla T4 ×2**, hỗ trợ retrieval Anh/Việt, instruction-aware embedding, Matryoshka dimensions, corpus Wikidata 100K đã xác minh, dual-worker serving và các notebook nghiệm thu công khai.

> **v1.0.0** là bản phát hành ổn định công khai đầu tiên dành cho cộng đồng sử dụng, review và kiểm tra khả năng tái lập.

## Bạn có thể làm gì

- Tạo Qwen3 embedding đã normalize ở 256, 1024 hoặc 4096 chiều.
- Tìm kiếm theo ý nghĩa trên corpus Wikidata **100.000 dòng Anh/Việt** đã xác minh.
- Chạy retrieval tiếng Anh, tiếng Việt và xuyên ngôn ngữ EN ↔ VI.
- So sánh query embedding có instruction với embedding thường.
- Phục vụ embedding/search request qua FastAPI.
- Dùng hai T4 worker persistent với bounded scheduler.
- Chạy Quick Demo ngắn có hướng dẫn hoặc hai notebook acceptance/qualification đầy đủ.

## Kaggle Quick Demo

Dùng:

`notebooks/kaggle-t4x2-quick-demo.ipynb`

Trước khi **Run All**:

1. Chọn **GPU T4 ×2**.
2. Bật **Internet** để clone/fetch đúng Git ref và cài package.
3. **Add Input → Models**: `dangkhoa2016/qwen-qwen3-embedding-8b`.
4. **Add Input → Datasets**: `dangkhoa2016/qwen3-embedding-8b-en-vi-100k-index`.

Input được mount read-only dưới `/kaggle/input`; trạng thái runtime có thể thay đổi nằm dưới `/kaggle/working`.

Quick Demo dùng lại prebuilt index 100K đã xác minh nhưng **mọi query của người dùng vẫn được embed live**. Demo gồm semantic search, cross-lingual EN/VI, instruction-aware ranking, semantic similarity, embedding dimensions linh hoạt và dual-T4 concurrency.

## Kiểm tra đầy đủ

Để review sâu hơn, chạy các notebook sau trong **các fresh Kaggle T4 ×2 session riêng biệt**:

| Notebook | Mục đích | Runtime điển hình |
|---|---|---:|
| `notebooks/kaggle-t4x2-production-demo.ipynb` | Build lại canonical index 100K và kiểm tra production lifecycle | ~1 giờ |
| `kaggle/demo.ipynb` | Qualification đầy đủ semantic/model/hardware/long-context | ~75 phút |

Không tái sử dụng `/kaggle/working` giữa các full run.

## Mô hình public serving

Repository được thiết kế để người dùng **clone và chạy trong Kaggle T4×2 session của chính mình**. Luồng mặc định giữ `EXPOSE_MODE=off`. **Cloudflare Quick Tunnel chỉ là tùy chọn** và khi bật rõ ràng sẽ được bảo vệ bằng API key đã cấu hình. Dự án **không phải một public inference endpoint được host cố định lâu dài**.

## Kiến trúc runtime

```text
Kaggle Model + Dataset inputs
          ↓
offline local model resolver
          ↓
FastAPI gateway
          ↓
bounded scheduler
       ↙      ↘
 T4 worker 0  T4 worker 1
       ↘      ↙
 embedding / search responses
          ↓
 verified 100K vector index
```

Topology mục tiêu dùng **hai model worker persistent độc lập**, mỗi worker trên một T4. Đây không phải tensor sharding.

## API

- `GET /health`
- `GET /ready`
- `GET /metrics`
- `GET /info`
- `POST /v1/embeddings`
- `POST /v1/search`

Xem [docs/api.vi.md](docs/api.vi.md).

## Xác minh

Các check CPU-safe:

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q
python scripts/check_bilingual_docs.py
python scripts/check_doc_links.py
python scripts/check_publication_policy.py
python -m compileall -q app dataset benchmark scripts
bash -n kaggle/*.sh scripts/*.sh
git diff --check
```

Qualification GPU/runtime tiếp tục chạy trên Kaggle T4 ×2.

## Tài liệu

- [Mục lục tài liệu](docs/index.vi.md)
- [Kiến trúc](docs/architecture.vi.md)
- [REST API](docs/api.vi.md)
- [Runtime Kaggle](docs/kaggle.vi.md)
- [Quick Demo](docs/quick-demo.vi.md)
- [Qualification](docs/qualification.vi.md)
- [Khả năng tái lập](docs/reproducibility.vi.md)
- [Phát triển](docs/development.vi.md)
- [Giới hạn](docs/limitations.vi.md)
- [Xử lý sự cố](docs/troubleshooting.vi.md)

## Model và dữ liệu

Model input:

`dangkhoa2016/qwen-qwen3-embedding-8b`

Quick Demo index:

`dangkhoa2016/qwen3-embedding-8b-en-vi-100k-index`

Canonical source corpus:

`dangkhoa2016/wikidata-en-vi-semantic-search-100k`

Mã nguồn dùng MIT License. Corpus structured data từ Wikidata dùng CC0; xem [dataset/LICENSE-DATA.vi.md](dataset/LICENSE-DATA.vi.md).

## Giấy phép

Copyright (c) 2026 Đăng Khoa <i.am@dangkhoa.dev>

Phát hành theo [MIT License](LICENSE).
