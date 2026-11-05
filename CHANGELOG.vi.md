# Lịch sử phát hành

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/CHANGELOG.md) | **Tiếng Việt**

Dự án sử dụng Semantic Versioning cho **các phiên bản mã nguồn được phát hành công khai**. Các mốc phát triển không được coi là phiên bản phát hành riêng.

## [1.0.0] — 2026-11-07

Bản phát hành công khai đầu tiên của **Remote-MCP**.

- MCP Gateway bảo vệ bằng OAuth, có giao diện đăng nhập và quản trị thiết bị.
- Agent chỉ kết nối ra ngoài, ghép nối từng thiết bị độc lập, có phê duyệt và thu hồi quyền.
- Thao tác file, thư mục và Git có kiểm soát trong workspace được cấp quyền.
- Chạy test có quản lý và CLI bất đồng bộ chỉ khi cấp quyền, với giới hạn log.
- Tài liệu song ngữ Anh/Việt, hướng dẫn triển khai và kiểm thử hồi quy trên Python 3.10 và 3.13.

Người triển khai phải tự cấu hình credentials, phân quyền và lưu trữ bền vững cho trạng thái ghép nối. Bản phát hành không phân phối device token hoặc cung cấp dịch vụ API công khai dùng chung.

[1.0.0]: https://github.com/dangkhoa2016/Remote-MCP/releases/tag/v1.0.0
