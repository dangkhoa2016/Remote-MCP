# Chính sách bảo mật

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/SECURITY.md) | **Tiếng Việt**

Remote-MCP cho phép truy cập có kiểm soát đến các workspace trên thiết bị được cấp quyền. Cấu hình không an toàn có thể làm lộ thông tin xác thực, mã nguồn hoặc khả năng thực thi lệnh từ xa.

## Phiên bản được hỗ trợ

Phiên bản mã nguồn công khai đầu tiên là **1.0.0**. Chính sách bảo mật áp dụng cho phiên bản hiện được duy trì; không có phiên bản 0.x nào được phát hành độc lập.

## Báo cáo lỗ hổng

**Không đăng công khai lỗ hổng, token, mã ghép nối hoặc thông tin đăng nhập lên GitHub Issues.** Liên hệ riêng người duy trì **Đăng Khoa <i.am@dangkhoa.dev>**, cung cấp cách tái hiện đã loại dữ liệu nhạy cảm và mô tả mức độ ảnh hưởng. Không truy cập hoặc tiết lộ dữ liệu của người khác.

## Lưu ý khi triển khai

- Coi việc chạy CLI qua Agent là thực thi mã với quyền của tài khoản hệ điều hành, **không phải OS sandbox**.
- Cấp quyền độc lập cho Gateway và Agent, chỉ trên máy đáng tin cậy.
- Lưu cơ sở dữ liệu đăng nhập, ghép nối thiết bị và OAuth trên bộ lưu trữ bền vững phù hợp.
- Không commit password, khóa ký OAuth, credentials ghép nối, token hoặc file môi trường.
- Không mở công khai các cổng Relay và MCP backend vốn chỉ bind loopback.
- Kiểm tra hostname, OAuth callback URL và quyền thực tế của từng deployment.

Xem [hướng dẫn triển khai](DEPLOY.vi.md), [checklist sẵn sàng phát hành](docs/RELEASE_READINESS.vi.md) và bản [hướng dẫn tiếng Anh](DEPLOY.md). CI thành công không đồng nghĩa đã được chứng nhận bảo mật.
