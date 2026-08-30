# Qwen3-Embedding-8B on Kaggle GPU T4×2

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](README.vi.md)

[![CI](https://github.com/dangkhoa2016/Qwen3-Embedding-8B-On-T4x2-GPU/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/dangkhoa2016/Qwen3-Embedding-8B-On-T4x2-GPU/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/dangkhoa2016/Qwen3-Embedding-8B-On-T4x2-GPU?display_name=tag&sort=semver)](https://github.com/dangkhoa2016/Qwen3-Embedding-8B-On-T4x2-GPU/releases/tag/v1.0.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10--3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Kaggle](https://img.shields.io/badge/Kaggle-T4%20%C3%972-20BEFF?logo=kaggle&logoColor=white)](https://www.kaggle.com/)
[![Model](https://img.shields.io/badge/Qwen3--Embedding--8B-4096d-6C63FF)](https://huggingface.co/Qwen/Qwen3-Embedding-8B)

A reproducible **Qwen3-Embedding-8B** semantic-search and embedding service for Kaggle **NVIDIA Tesla T4 ×2**, with English/Vietnamese retrieval, instruction-aware embeddings, Matryoshka dimensions, a verified Wikidata 100K corpus, dual-worker serving, and public acceptance notebooks.

> **v1.0.0** is the first public stable release for community use, review, and reproducibility testing.

## What you can do

- Generate normalized Qwen3 embeddings at 256, 1024, or 4096 dimensions.
- Search a verified **100,000-row English/Vietnamese Wikidata corpus** by meaning.
- Run English, Vietnamese, and cross-lingual EN ↔ VI retrieval.
- Compare instruction-aware query embeddings against plain embeddings.
- Serve embedding/search requests through FastAPI.
- Exercise two persistent T4 workers with bounded scheduling.
- Run a short guided Quick Demo or deeper full acceptance/qualification notebooks.

## Kaggle Quick Demo

Use:

`notebooks/kaggle-t4x2-quick-demo.ipynb`

Before **Run All**:

1. Select **GPU T4 ×2**.
2. Enable **Internet** for the pinned Git clone/fetch and package installation.
3. **Add Input → Models**: `dangkhoa2016/qwen-qwen3-embedding-8b`.
4. **Add Input → Datasets**: `dangkhoa2016/qwen3-embedding-8b-en-vi-100k-index`.

Attached inputs stay read-only below `/kaggle/input`; mutable runtime state stays below `/kaggle/working`.

The Quick Demo reuses a verified prebuilt 100K index but embeds **every user query live**. It demonstrates semantic search, EN/VI cross-lingual retrieval, instruction-aware ranking, semantic similarity, flexible embedding dimensions, and dual-T4 concurrency.

## Full verification

For deeper review, run these in **separate fresh Kaggle T4 ×2 sessions**:

| Notebook | Purpose | Typical runtime |
|---|---|---:|
| `notebooks/kaggle-t4x2-production-demo.ipynb` | Rebuild the canonical 100K index and validate the production lifecycle | ~1 hour |
| `kaggle/demo.ipynb` | Full semantic/model/hardware/long-context qualification | ~75 minutes |

Do not reuse `/kaggle/working` state between full runs.

## Public serving model

This repository is designed to **clone/run in your own Kaggle T4×2 session**. The normal path keeps `EXPOSE_MODE=off`. **Cloudflare Quick Tunnel is optional** and, when explicitly enabled, is protected by the configured API key. This project is **not a permanently hosted public inference endpoint**.

## Runtime architecture

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

The intended topology uses **two independent persistent model workers**, one per T4. It is not tensor sharding.

## API

- `GET /health`
- `GET /ready`
- `GET /metrics`
- `GET /info`
- `POST /v1/embeddings`
- `POST /v1/search`

See [docs/api.md](docs/api.md).

## Validation

CPU-safe checks:

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

GPU/runtime qualification remains on Kaggle T4 ×2.

## Documentation

- [Documentation index](docs/index.md)
- [Architecture](docs/architecture.md)
- [REST API](docs/api.md)
- [Kaggle runtime](docs/kaggle.md)
- [Quick Demo](docs/quick-demo.md)
- [Qualification](docs/qualification.md)
- [Reproducibility](docs/reproducibility.md)
- [Development](docs/development.md)
- [Limitations](docs/limitations.md)
- [Troubleshooting](docs/troubleshooting.md)

## Model and data

Model input:

`dangkhoa2016/qwen-qwen3-embedding-8b`

Quick Demo index:

`dangkhoa2016/qwen3-embedding-8b-en-vi-100k-index`

Canonical source corpus:

`dangkhoa2016/wikidata-en-vi-semantic-search-100k`

The software is MIT licensed. The structured Wikidata-derived corpus is CC0; see [dataset/LICENSE-DATA.md](dataset/LICENSE-DATA.md).

## License

Copyright (c) 2026 Đăng Khoa <i.am@dangkhoa.dev>

Released under the [MIT License](LICENSE).
