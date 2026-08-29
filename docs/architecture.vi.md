# Kiến trúc

> 🌐 Language / Ngôn ngữ: [English](architecture.md) | **Tiếng Việt**

## Topology runtime

Ứng dụng gồm FastAPI gateway phía CPU và hai embedding worker persistent, mỗi worker bind vào một Tesla T4 của Kaggle.

```text
Kaggle Inputs read-only
  ├─ model Qwen3-Embedding-8B
  └─ canonical dataset / verified index
                ↓
         FastAPI gateway
                ↓
      bounded token scheduler
          ↙           ↘
     cuda:0 worker  cuda:1 worker
          ↘           ↙
       normalized embeddings
                ↓
      semantic-search index
```

Model không tensor-shard. Mỗi worker sở hữu một model replica độc lập.

## Model path offline-first

Model resolver chỉ chấp nhận path dưới `/kaggle/input`. Các offline flag của hệ sinh thái Hugging Face được bật và model chỉ load từ file local.

## Scheduler

Scheduler giới hạn request theo số item, estimated tokens, sequence length, queue cost và worker readiness. Nó giữ nguyên thứ tự input và xuất per-worker metrics.

## Search

Canonical index lưu các corpus vector đã normalize, căn hàng với dữ liệu Wikidata song ngữ. Search so sánh vector và trả QID cùng label tiếng Anh/tiếng Việt.

## Biên bảo mật

Luồng Kaggle bình thường chỉ chạy local. External exposure là tùy chọn, bắt buộc authentication và phải bật rõ ràng.

## Trạng thái có thể thay đổi

Input read-only nằm dưới `/kaggle/input`; index, log và evidence được ghi dưới `/kaggle/working`.
