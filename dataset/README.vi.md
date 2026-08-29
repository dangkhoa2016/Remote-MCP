# Bộ dựng Dataset Wikidata EN/VI CC0 canonical

> 🌐 Language / Ngôn ngữ: [English](README.md) | **Tiếng Việt**

Builder này tạo corpus structured data có khả năng tái lập dùng bởi dự án Qwen3-Embedding-8B trên Kaggle T4×2.

## Chính sách nguồn dữ liệu

Chỉ thu thập các field có cấu trúc từ Wikidata:

- QID;
- label tiếng Anh/tiếng Việt;
- description tiếng Anh/tiếng Việt;
- alias tiếng Anh/tiếng Việt;
- QID `P31` (`instance of`) trực tiếp.

Không lấy nội dung bài Wikipedia, tin tức, Common Crawl hoặc prose tùy ý từ website.

## Thu thập

Builder dùng các interface Wikimedia chính thức:

1. Wikidata Query Service để tìm QID.
2. Wikibase Action API `wbgetentities` để hydrate entity theo batch.

Acquisition client chạy tuần tự, tuân thủ retry/backoff, dùng User-Agent mô tả rõ và giữ resumable state.

## Vì sao acquisition tách khỏi Kaggle demo

Public inference workflow không nên phụ thuộc tình trạng live của Wikidata. Hãy build corpus một lần, publish thành Kaggle Dataset bất biến và attach qua Kaggle Input.

## Build

```bash
python -m pip install -r requirements-dataset.txt
python dataset/build_public_wikidata.py --help
```

Xem [LICENSE-DATA.vi.md](LICENSE-DATA.vi.md) để biết license dữ liệu.
