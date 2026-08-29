# Khả năng tái lập

> 🌐 Language / Ngôn ngữ: [English](reproducibility.md) | **Tiếng Việt**

## Danh tính source

Public notebook in selected Git ref và exact commit SHA.

## Danh tính model

Runtime weights chỉ đến từ Kaggle Model đã attach. Resolver chỉ hoạt động dưới `/kaggle/input` và xác minh local model layout.

## Danh tính dữ liệu

Canonical dataset và Quick Demo index mang checksum, row count, dimensions và provenance metadata.

## Chính sách fresh session

Full production acceptance và qualification nên chạy trong các fresh Kaggle session riêng. Không tái sử dụng mutable state dưới `/kaggle/working` giữa hai run.

## Release artifact

Release archive được scan, re-extract, checksum-verify và tạo từ publication revision.

## Cách hiểu evidence

GPU evidence lịch sử tiếp tục là evidence cho đúng SHA của nó. Documentation/presentation amendment có thể kiểm tra offline; executable change cần rerun phù hợp.
