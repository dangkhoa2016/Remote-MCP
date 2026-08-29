# Canonical Wikidata EN/VI CC0 Dataset Builder

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](README.vi.md)

This builder creates the reproducible structured-data corpus used by the Qwen3-Embedding-8B Kaggle T4×2 project.

## Source policy

Only structured Wikidata fields are acquired:

- QID;
- English/Vietnamese labels;
- English/Vietnamese descriptions;
- English/Vietnamese aliases;
- direct `P31` (`instance of`) QIDs.

Wikipedia article bodies, news text, Common Crawl and arbitrary website prose are excluded.

## Acquisition

The builder uses official Wikimedia interfaces:

1. Wikidata Query Service for QID discovery.
2. Wikibase Action API `wbgetentities` for batched entity hydration.

The acquisition client is sequential, respects retry/backoff signals, identifies itself with a descriptive User-Agent, and keeps resumable state.

## Why acquisition is separate from the Kaggle demo

The public inference workflow must not depend on live Wikidata availability. Build the corpus once, publish it as an immutable Kaggle Dataset, and attach it through Kaggle Input.

## Build

```bash
python -m pip install -r requirements-dataset.txt
python dataset/build_public_wikidata.py --help
```

See [LICENSE-DATA.md](LICENSE-DATA.md) for data licensing.
