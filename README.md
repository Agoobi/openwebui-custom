# openwebui-custom

Tùy biến Open WebUI để chủ shop xem **hộp thư chatbot website** (skill `chatbot-tu-van` của Hermes) trực quan, không
phải đọc từng chat. Không fork Open WebUI: chỉ dùng hai file Open WebUI tự nạp trên mọi trang, `/static/custom.css`
và `/static/loader.js`.

Chủ shop thấy:

- Chat ghim **Tổng quan hộp thư**: số liệu hôm nay (hội thoại, lead, cần xử lý, bot bị chặn) và bảng khách; bấm một
  dòng để mở chat của khách đó.
- 3 folder **Cần xử lý / Đang chat / Đã xong**, chat tự chuyển nhóm, có số chưa đọc.
- Mỗi khách 1 chat: thẻ khách ở đầu (tên, SĐT, nhu cầu, trang đang xem, nút **Đã gọi / Xong / Mở lại**), thẻ sự
  kiện lead ngay trong hội thoại, tin mới hiện ngay không cần tải lại trang.

Dữ liệu và thẻ do Hermes ghi (`owui_inbox.py` trong skill). Repo này lo phần trình bày và mở chat từ bảng tổng quan.
Hợp đồng giữa hai bên: [docs/dong-bo.md](docs/dong-bo.md).

## Cài

Open WebUI cài bằng pip + systemd (như trên VPS do Coquifly dựng):

```bash
git clone https://github.com/Agoobi/openwebui-custom.git /opt/openwebui-custom
sudo /opt/openwebui-custom/deploy/install.sh            # mặc định /opt/open-webui/venv, service open-webui
```

Chạy lại lệnh này sau mỗi lần nâng cấp Open WebUI (pip ghi đè thư mục static).

Docker:

```bash
docker build -t openwebui-custom .
```

## Phiên bản

Đã kiểm với **Open WebUI 0.11.4**. `install.sh` cảnh báo nếu bản cài khác. Nâng cấp thì đi qua danh sách trong
[docs/dong-bo.md](docs/dong-bo.md#kiểm-lại-khi-nâng-cấp-open-webui).

## Giấy phép Open WebUI

Giấy phép Open WebUI cấm đổi, ẩn tên và logo "Open WebUI" khi một bản có quá 50 người dùng trong 30 ngày (trừ bản
enterprise). Repo này không đụng tới thương hiệu.
