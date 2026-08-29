# Qualification

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](qualification.vi.md)

Qualification separates a short showcase from release evidence.

## Quick Demo

The Quick Demo proves the public user flow, live queries, bilingual retrieval, instruction-aware ranking, flexible dimensions, and dual-worker activity.

## Full production acceptance

`notebooks/kaggle-t4x2-production-demo.ipynb` rebuilds the canonical 100K index from scratch and validates the production lifecycle on a fresh T4×2 session.

## Full qualification

`kaggle/demo.ipynb` runs the deeper semantic, model-capability, hardware, long-context, regression, and evidence checks.

## Evidence boundary

Runtime evidence is bound to the exact Git revision that produced it. If executable notebook logic changes, exact-SHA GPU acceptance must be rerun before the new revision inherits the PASS claim.

## Fail-closed policy

Missing model/data inputs, invalid fingerprints, checksum mismatches, unsupported GPU topology, worker failure, or hard runtime-limit violations fail the acceptance path instead of being ignored.
