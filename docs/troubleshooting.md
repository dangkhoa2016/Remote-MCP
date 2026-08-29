# Troubleshooting

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](troubleshooting.vi.md)

## Model not found

Confirm `dangkhoa2016/qwen-qwen3-embedding-8b` is attached through **Add Input → Models**. Do not copy it into `/kaggle/working`.

## Quick Demo index not found

Attach `dangkhoa2016/qwen3-embedding-8b-en-vi-100k-index` through **Add Input → Datasets**.

## Only one GPU appears

Stop the session and select **GPU T4 ×2**. The supported public workflow fails closed when the expected topology is unavailable.

## Bootstrap package error

Keep Internet enabled during bootstrap. After dependencies and Kaggle Inputs are available, model/data loading itself is local.

## Checksum or fingerprint failure

Do not bypass the check. Detach stale inputs, attach the expected published artifact, and start a fresh session.

## Startup takes longer than another run

Kaggle startup/model load latency can vary. Judge the run by readiness, failures and the configured runtime ceiling rather than a single previous startup time.
