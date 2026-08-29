# Development

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](development.vi.md)

## Local CPU-safe setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[test]
```

## Required checks

```bash
python -m pytest -q
python scripts/check_bilingual_docs.py
python scripts/check_doc_links.py
python scripts/check_publication_policy.py
python -m compileall -q app dataset benchmark scripts
bash -n kaggle/*.sh scripts/*.sh
git diff --check
```

## Contribution scope

Keep commits focused. Public Markdown documents are maintained as EN/VI pairs. Changes that alter GPU runtime behavior or acceptance semantics require new runtime evidence.

## Kaggle-only checks

Real Qwen3 model loading, VRAM behavior, T4 worker activity and full corpus acceptance require Kaggle T4×2.
