# Phát triển

> 🌐 Language / Ngôn ngữ: [English](development.md) | **Tiếng Việt**

## Thiết lập CPU-safe local

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[test]
```

## Các check bắt buộc

```bash
python -m pytest -q
python scripts/check_bilingual_docs.py
python scripts/check_doc_links.py
python scripts/check_publication_policy.py
python -m compileall -q app dataset benchmark scripts
bash -n kaggle/*.sh scripts/*.sh
git diff --check
```

## Phạm vi contribution

Giữ commit tập trung. Tài liệu Markdown public được duy trì theo cặp EN/VI. Thay đổi ảnh hưởng GPU runtime hoặc acceptance semantics cần runtime evidence mới.

## Check chỉ chạy trên Kaggle

Model loading thật, VRAM behavior, hoạt động T4 worker và full corpus acceptance cần Kaggle T4×2.
