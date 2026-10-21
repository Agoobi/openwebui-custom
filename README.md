# openwebui-custom

Chatbot tư vấn trên website, quản lý hoàn toàn trong **Open WebUI**: chủ shop bật/tắt, sửa thông tin, nạp kiến
thức, xem khách và lead ngay trong Open WebUI. Không cần cài gì bên Hermes; chatbot gọi thẳng LLM nên khách website
không chạm được tới công cụ của trợ lý. Không fork Open WebUI: thêm một gói Python nhỏ (`backend/cqf_openwebui`) và
vài trang tĩnh.

Sidebar Open WebUI có thêm 3 mục (dưới Search), mở ngay trong vùng nội dung, sidebar giữ nguyên:

| Mục | Làm gì |
| --- | --- |
| **Hộp thư** (kèm số khách cần xử lý) | Danh sách khách (Tất cả / Cần xử lý / Đang chat / Đã xong, lọc kênh, tìm, mới nhất / chờ lâu nhất), hội thoại, thẻ sự kiện (để lại thông tin, cần nhân viên, bot không trả lời được), thông tin khách, nút Đã gọi / Xong / Mở lại. |
| **Chatbot** | Bật/tắt, mã nhúng (1 dòng script), thông tin shop, khung chat (tiêu đề, lời chào, màu), website được gắn, **số lần tra kiến thức tối thiểu** (mặc định 4), xin khách gì khi không có câu trả lời, LLM (URL, model, key, thử kết nối), thử chatbot ngay trên trang. |
| **Kiến thức** | Kiểu Obsidian: tải file Word / Excel / CSV / PDF có chữ / TXT / MD lên (kéo thả được) thành ghi chú, xem / sửa Markdown, `[[liên kết]]` giữa ghi chú, mục lục, ghi chú trỏ tới, bật/tắt từng ghi chú, cảnh báo khi số liệu sửa tay khác file gốc, **thử tìm như bot**. |

## Một lượt trả lời

1. Hệ thống tự tra Kiến thức **ít nhất N lần** (cài trên trang Chatbot, mặc định 4) bằng các cách diễn đạt khác nhau:
   nguyên câu, ghép câu trước, từ khoá, từng ý, từng từ khoá.
2. Gọi LLM (chuẩn OpenAI) kèm các đoạn tìm được và 4 tool: `tim_kien_thuc`, `doc_tai_lieu` (tra thêm khi cần),
   `luu_khach_hang`, `chuyen_nhan_vien`.
3. Chặn câu trả lời có giá, %, SĐT, số tài khoản, thời hạn không có trong tài liệu đã tra: khách nhận câu xin liên
   hệ, chủ shop thấy sự kiện "Bot không trả lời được" trong Hộp thư.
4. Khách để lại thông tin / cần nhân viên → vào **Cần xử lý**. Khách để số mà bot không lưu: hệ thống vẫn bắt số đó.

Dữ liệu ở `<DATA_DIR của Open WebUI>/cqf/` (`settings.json`, `knowledge/`, `sources/`, `inbox/`), quyền 600.
Không ghi gì vào chat / folder của Open WebUI.

## Cài

Open WebUI cài bằng pip + systemd (như trên VPS do Coquifly dựng):

```bash
git clone https://github.com/Agoobi/openwebui-custom.git /opt/openwebui-custom
sudo /opt/openwebui-custom/deploy/install.sh            # mặc định /opt/open-webui/venv, service open-webui
```

Script: chép trang tĩnh, thêm `cqf_openwebui.pth` vào venv, thêm drop-in systemd chạy
`python -m cqf_openwebui serve` (= `open-webui serve` + `/api/v1/cqf`), cài `poppler-utils` (đọc PDF). Chạy lại sau
mỗi lần nâng cấp Open WebUI. Gỡ: xoá `/etc/systemd/system/open-webui.service.d/cqf.conf`, `daemon-reload`, restart.

Sau khi cài: mở Open WebUI → **Chatbot**: điền LLM, thông tin shop, website, bật; **Kiến thức**: tải tài liệu lên;
dán mã nhúng vào website.

## API (`/api/v1/cqf`)

- Công khai (khung chat, kiểm Origin trong danh sách website): `GET /webchat/widget.js`, `POST /webchat/chat`.
- Quản trị (đăng nhập Open WebUI, vai trò admin, dùng `get_admin_user` của Open WebUI): `/settings`,
  `/settings/test`, `/kb*`, `/inbox/*`, `/status`.

## Phiên bản

Đã kiểm với **Open WebUI 0.11.4**, `UVICORN_WORKERS=1` (mặc định). Nâng cấp thì kiểm lại:

1. `src/app.html` vẫn nạp `/static/loader.js`, `/static/custom.css`; `/static` phục vụ thư mục con.
2. `open-webui serve` vẫn chỉ đặt `FROM_INIT_PY`, `WEBUI_SECRET_KEY` rồi `uvicorn.run('open_webui.main:app')`.
3. Sidebar còn `#sidebar-search-button` trong 1 hàng `div`; token phiên vẫn ở `localStorage.token`.
4. `open_webui.utils.auth.get_admin_user`, `open_webui.env.DATA_DIR` còn nguyên.

## Giấy phép Open WebUI

Giấy phép Open WebUI cấm đổi, ẩn tên và logo "Open WebUI" khi một bản có quá 50 người dùng trong 30 ngày (trừ bản
enterprise). Repo này không đụng tới thương hiệu.
