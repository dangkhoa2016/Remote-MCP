# Cai Agent bang mot lenh (Render)

Tai va xem script truoc: curl -fsSLo setup.sh https://remote-mcp-ka1p.onrender.com/setup.sh ; sau do bash setup.sh.

Neu tin cay server, dung: curl -fsSL https://remote-mcp-ka1p.onrender.com/setup.sh | bash

Voi wget phai dung -qO-: wget -qO- https://remote-mcp-ka1p.onrender.com/setup.sh | bash

Script hoi device ID, duong dan workspace tuyet doi da ton tai va device token (nhap an). Device token phai duoc cau hinh truoc o KRW_DEVICE_TOKENS_JSON tren Render. Khong gui token qua chat hoac URL.

Ma Agent duoc cai vao ~/.local/share/krw-agent. Thong tin xac thuc luu ngoai workspace tai ~/.config/krw-agent/agent.env voi quyen 0600. Chay lai Agent bang ~/.local/share/krw-agent/start.sh .

Archive chi chua source Agent trong danh sach duoc phep, co SHA-256 kiem tra truoc giai nen. Command execution van bi khoa. Khi Colab reset thi Agent van offline. Nen doc script truoc khi chay pipe-to-bash.
