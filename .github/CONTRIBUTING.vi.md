# Đóng góp

> 🌐 Language / Ngôn ngữ: [English](CONTRIBUTING.md) | **Tiếng Việt**

Cảm ơn bạn đã giúp cải thiện dự án.

## Nguyên tắc

- Giữ commit tập trung và dễ review.
- Duy trì tài liệu Markdown public theo cặp tiếng Anh/tiếng Việt.
- Không làm yếu các check fail-closed cho model/data/input.
- Không claim GPU acceptance cho source revision chưa tạo ra evidence đó.
- Giữ canonical QID khi cải thiện phần trình bày human-readable.

## Development checks

```bash
python -m pytest -q
python scripts/check_bilingual_docs.py
python scripts/check_doc_links.py
python scripts/check_publication_policy.py
python -m compileall -q app dataset benchmark scripts
bash -n kaggle/*.sh scripts/*.sh
git diff --check
```

GPU qualification thật tiếp tục chạy trên Kaggle T4×2.
