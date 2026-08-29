# Kaggle T4×2 Runtime

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](kaggle.vi.md)

## Required session

- Accelerator: **NVIDIA Tesla T4 ×2**
- Internet: ON during bootstrap/package installation
- Model input: `dangkhoa2016/qwen-qwen3-embedding-8b`

Quick Demo additionally requires:

- Dataset: `dangkhoa2016/qwen3-embedding-8b-en-vi-100k-index`

Full production/qualification runs use the canonical dataset:

- `dangkhoa2016/wikidata-en-vi-semantic-search-100k`

## Input contract

Use Kaggle **Add Input**. Do not copy or modify attached artifacts below `/kaggle/input`.

The resolver fails closed if the required model/data artifact is missing or ambiguous.

## Notebooks

- Quick public showcase: `notebooks/kaggle-t4x2-quick-demo.ipynb`
- Full production acceptance: `notebooks/kaggle-t4x2-production-demo.ipynb`
- Full qualification: `kaggle/demo.ipynb`

Run the two full notebooks in separate fresh sessions.

## Bootstrap

`kaggle/bootstrap.sh` verifies CUDA/T4 availability, prepares dependencies, enforces read-only input policy, and prints the exact environment used by acceptance.
