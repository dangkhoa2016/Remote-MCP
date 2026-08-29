# Runtime Kaggle T4×2

> 🌐 Language / Ngôn ngữ: [English](kaggle.md) | **Tiếng Việt**

## Session bắt buộc

- Accelerator: **NVIDIA Tesla T4 ×2**
- Internet: bật trong bước bootstrap/cài package
- Model input: `dangkhoa2016/qwen-qwen3-embedding-8b`

Quick Demo cần thêm:

- Dataset: `dangkhoa2016/qwen3-embedding-8b-en-vi-100k-index`

Full production/qualification dùng canonical dataset:

- `dangkhoa2016/wikidata-en-vi-semantic-search-100k`

## Contract của input

Dùng **Add Input** của Kaggle. Không copy hoặc sửa artifact đã attach dưới `/kaggle/input`.

Resolver fail-closed nếu model/data artifact bắt buộc bị thiếu hoặc ambiguous.

## Notebook

- Public showcase nhanh: `notebooks/kaggle-t4x2-quick-demo.ipynb`
- Full production acceptance: `notebooks/kaggle-t4x2-production-demo.ipynb`
- Full qualification: `kaggle/demo.ipynb`

Hai full notebook phải chạy trong các fresh session riêng.

## Bootstrap

`kaggle/bootstrap.sh` kiểm tra CUDA/T4, chuẩn bị dependency, enforce read-only input policy và in chính xác environment dùng cho acceptance.
