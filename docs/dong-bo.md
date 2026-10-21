# Đồng bộ Hermes → Open WebUI (hộp thư chatbot)

Hermes (skill `chatbot-tu-van`, file `owui_inbox.py`) là bên **duy nhất** ghi vào Open WebUI, qua API bằng API key
của tài khoản chủ shop. Repo này chỉ lo phần hiển thị trong trình duyệt. Hai bên hẹn nhau ở những điểm sau; đổi ở
một bên thì sửa bên kia.

## Hermes ghi gì

| Thứ | Quy ước |
| --- | --- |
| Folder | `Cần xử lý`, `Đang chat`, `Đã xong` ở gốc. Hermes tự tạo và chuyển chat theo trạng thái. `loader.js` nhận ra folder theo **đúng tên** này. |
| Chat khách | Mỗi khách 1 chat, tên `<Tên> · <SĐT>` hoặc `Khách <mã> · <câu hỏi đầu>`. Tin đầu là thẻ khách (HTML trong `embeds`). |
| Chat tổng quan | Tên đúng `Tổng quan hộp thư`, được ghim. Tin duy nhất chứa bảng HTML. |
| Cập nhật trực tiếp | Sau mỗi lần ghi, Hermes gọi `POST /api/v1/chats/{id}/messages/{mid}/event` với `chat:reload` (tab đang mở tải lại chat) và `chat:title` (sidebar sắp xếp lại). Chat được ghi có `history` nên tự thành chưa đọc. |

## HTML nhúng nói chuyện với trang

Thẻ chạy trong iframe sandbox của Open WebUI (`allow-scripts`, không cùng origin), nên không tự mở trang được:

- Dòng trong bảng tổng quan gửi `parent.postMessage({type: 'cqf-open-chat', chatId}, '*')`; `loader.js` kiểm tra
  `chatId` là UUID và tin đến từ một iframe trong trang rồi mở `/c/<chatId>`.
- Nút **Đã gọi / Xong / Mở lại** trên thẻ khách gọi thẳng Hermes: `POST <webchat.public_url>/owui/action` với
  `{conv, sig, action}` (chữ ký HMAC theo từng chat). Hermes đổi trạng thái, chuyển folder, rồi phát `chat:reload`.

## Kiểm lại khi nâng cấp Open WebUI

Bản tùy biến bám vào cấu trúc của 0.11.4:

1. `src/app.html` vẫn nạp `/static/loader.js` và `/static/custom.css`.
2. Nút folder có `id="folder-<id>-button"` và tên nằm trong `.truncate`.
3. Tin nhắn vẫn hiển thị `message.embeds` và xử lý sự kiện `chat:reload`, `chat:title`.
4. API: `/api/v1/folders/`, `/api/v1/chats/new`, `/api/v1/chats/{id}`, `/api/v1/chats/{id}/folder`, `/api/v1/chats/{id}/pin`.
