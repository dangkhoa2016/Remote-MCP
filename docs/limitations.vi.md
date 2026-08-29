# Giới hạn

> 🌐 Language / Ngôn ngữ: [English](limitations.md) | **Tiếng Việt**

- Runtime mục tiêu là Kaggle NVIDIA Tesla T4 ×2.
- Topology serving dự kiến dùng hai model replica độc lập, không phải tensor sharding.
- Dự án không tuyên bố hai GPU luôn nhanh chính xác gấp 2 lần một GPU.
- Corpus vector của Quick Demo được tính sẵn; query người dùng vẫn chạy live.
- Full rebuild 100K cần production-acceptance notebook và nhiều runtime hơn đáng kể.
- Chất lượng search phụ thuộc cả corpus coverage lẫn embedding quality.
- External exposure tùy chọn chỉ là demo tạm thời, không phải hosted service có SLA lâu dài.
- Runtime có thể dao động giữa các Kaggle session.
