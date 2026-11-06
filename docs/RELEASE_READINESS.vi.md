# Remote-MCP 1.0.0 — Checklist phát hành

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/RELEASE_READINESS.md) | **Tiếng Việt**

**Lần phát hành công khai đầu tiên dự kiến: 1.0.0.** Không có các bản phát hành sản phẩm 0.x riêng lẻ. Các mốc phát triển không được coi là release tag.

## Kết quả đã xác minh trên mã nguồn hiện tại

- Lịch sử Git Remote-MCP được chia thành 14 commit tính năng và tài liệu, file trong mỗi commit chỉ có trạng thái A.
- Full regression Python: 209 bài test PASS trong lần nghiệm thu gần nhất.
- Giao diện đăng nhập/Devices và công cụ Agent được thử nghiệm trên hạ tầng đã kết nối.
- Nhánh GitHub main là nguồn triển khai; push thành công chưa chứng minh Render đã sử dụng revision đó.

## Những mục còn cần xác minh trên production

- [ ] GitHub Actions PASS trên các phiên bản Python được hỗ trợ (3.10 và 3.13).
- [ ] Health của Gateway đang chạy trả về phiên bản **1.0.0** sau khi triển khai.
- [ ] Nghiệm thu đăng nhập và thao tác Devices trực tiếp trên giao diện live.
- [ ] Tối thiểu hai Agent thật kết nối độc lập và reconnect sau khi khởi động lại một Agent mà không cần pairing mới.
- [ ] Xác minh SQLite OAuth/enrollment vẫn lưu bền sau khi thay Gateway, cùng khả năng backup/restore nhất quán.
- [ ] Thử nghiệm thu hồi thiết bị và phân quyền trên môi trường kiểm thử riêng.
- [ ] Xác nhận tag Git `v1.0.0` trỏ đúng commit mã nguồn của lần phát hành đầu tiên.

## Lưu ý vận hành

- Agent đang chạy có thể tự reconnect khi mất mạng; Colab runtime đã tắt không thể tự khởi động.
- Các job đang xử lý và hàng đợi của Relay ở RAM, không bảo đảm tồn tại qua Gateway restart.
- Để lưu bền database, Render phải có mount thực sự; thư mục ghi được không đủ.
- Test và CLI đều thực thi mã nguồn, **không** phải OS sandbox.
- Không làm gián đoạn production chỉ để hoàn thành checklist.
