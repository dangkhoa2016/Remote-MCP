# Contributing

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](CONTRIBUTING.vi.md)

Thank you for helping improve this project.

## Ground rules

- Keep commits focused and reviewable.
- Keep public Markdown documentation in English/Vietnamese pairs.
- Do not weaken fail-closed model/data/input checks.
- Do not claim GPU acceptance for a source revision that has not produced that evidence.
- Preserve canonical QID fields when improving human-readable presentation.

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

Real GPU qualification remains on Kaggle T4×2.
