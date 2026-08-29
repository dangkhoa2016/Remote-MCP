# Quick Demo

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](quick-demo.vi.md)

The Quick Demo is the recommended public entry point.

It uses the verified prebuilt dataset `dangkhoa2016/qwen3-embedding-8b-en-vi-100k-index`, containing 100,000 aligned Wikidata rows and 4096-dimensional normalized corpus vectors.

## What remains live

- Model startup
- Every user query embedding
- English/Vietnamese semantic search
- Cross-lingual retrieval
- Instruction-aware embedding calls
- Similarity calculations
- Flexible-dimension embedding calls
- Concurrent request serving

Only the expensive corpus-wide vector build is precomputed.

## Reading results

Search tables preserve Wikidata **QID** and show human-readable English/Vietnamese labels beside it.

Cross-lingual sections compare equivalent EN/VI queries. Instruction-aware sections compare the same text encoded as ordinary content versus retrieval query text.

## Runtime target

The public target is 5–10 minutes, with a hard 15-minute ceiling. Startup time can vary between Kaggle sessions.

## Deeper verification

Use the production and qualification notebooks for full corpus rebuild and deeper evidence.
