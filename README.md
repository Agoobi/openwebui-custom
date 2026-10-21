# openwebui-custom

Trang **Hộp thư** trong Open WebUI cho chatbot website của Hermes (skill `chatbot-tu-van`): chủ shop xem khách,
hội thoại và lead ở một màn hình riêng, không phải lục chat hay folder. Không fork Open WebUI: chỉ thêm file tĩnh
và hai file Open WebUI tự nạp trên mọi trang (`/static/loader.js`, `/static/custom.css`).

- Sidebar có thêm hàng **Hộp thư** (dưới Search) kèm số khách cần xử lý.
- Trang Hộp thư hai cột như hộp thư email: bên trái danh sách khách (Tất cả / Cần xử lý / Đang chat / Đã xong, lọc
  kênh, tìm, sắp theo mới nhất hoặc chờ lâu nhất); bên phải hội thoại, thẻ sự kiện (khách để lại thông tin, cần
  nhân viên, bot không trả lời được), thông tin khách, nút **Đã gọi / Xong / Mở lại**. Tự làm mới vài giây một
  lần, chạy trên điện thoại, theo chế độ sáng/tối của Open WebUI.

Dữ liệu ở Hermes; Hermes không ghi gì vào Open WebUI. Cách hai bên nói chuyện: [docs/dong-bo.md](docs/dong-bo.md).

## Cài

Open WebUI cài bằng pip + systemd (như trên VPS do Coquifly dựng):

```bash
git clone https://github.com/Agoobi/openwebui-custom.git /opt/openwebui-custom
sudo HERMES_INBOX_URL=https://bot.shop.vn /opt/openwebui-custom/deploy/install.sh
```

`HERMES_INBOX_URL` là URL https của bot Hermes (plugin webchat). Chạy lại sau mỗi lần nâng cấp Open WebUI (pip ghi đè
thư mục static); bỏ `HERMES_INBOX_URL` thì giữ cấu hình cũ.

Phía Hermes điền `open_webui.url` và `open_webui.public_url` trong `chatbot/settings.json` (xem skill).

Docker:

```bash
docker build --build-arg HERMES_INBOX_URL=https://bot.shop.vn -t openwebui-custom .
```

## Phiên bản

Đã kiểm với **Open WebUI 0.11.4**. `install.sh` cảnh báo nếu bản cài khác. Nâng cấp thì đi qua danh sách trong
[docs/dong-bo.md](docs/dong-bo.md#kiểm-lại-khi-nâng-cấp-open-webui).

## Giấy phép Open WebUI

Giấy phép Open WebUI cấm đổi, ẩn tên và logo "Open WebUI" khi một bản có quá 50 người dùng trong 30 ngày (trừ bản
enterprise). Repo này không đụng tới thương hiệu.
