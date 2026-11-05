# Đóng góp cho Remote-MCP

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/CONTRIBUTING.md) | **Tiếng Việt**

Cảm ơn bạn đã đóng góp cho Remote-MCP. Thay đổi cần có phạm vi rõ ràng, dễ review và đảm bảo an toàn cho hệ thống truy cập workspace từ xa có xác thực.

## Trước khi đề xuất thay đổi

1. Đọc [README tiếng Việt](README.vi.md) hoặc [README tiếng Anh](README.md), kiểm tra các issue hiện có.
2. Khi báo lỗi, cung cấp ví dụ tái hiện tối thiểu đã loại dữ liệu nhạy cảm, kết quả mong đợi, kết quả thực tế và phiên bản mã nguồn.
3. Khi đề xuất chức năng, nêu lý do, thay đổi về quyền truy cập và rủi ro tương thích.
4. Chạy test tự động cùng các kiểm tra cú pháp liên quan trên phiên bản Python được hỗ trợ.

## Kiểm tra cục bộ

    python -m pip install -r requirements-dev.txt
    python -m compileall -q agent gateway tests
    bash -n gateway/setup.sh
    python -m pytest -q

CI chạy trên Python 3.10 và 3.13. Fixture kiểm thử không được chứa mật khẩu, device token, dữ liệu database thật hoặc credentials cloud.

## Review và phát hành

Dùng commit message mô tả rõ thay đổi; tránh tiêu đề chung chung như "fix". Duy trì tài liệu tiếng Anh và tiếng Việt tách biệt với nội dung chức năng và bảo mật nhất quán. Thay đổi liên quan quyền Agent, OAuth, chạy CLI hoặc lưu bền trạng thái ghép nối cần review bảo mật riêng. Không viết lại hoặc xuất bản lịch sử Git nếu chưa được chủ repository cho phép.

Báo cáo bảo mật theo [SECURITY.vi.md](SECURITY.vi.md), không qua issue công khai.

**Người duy trì:** Đăng Khoa <i.am@dangkhoa.dev>.
