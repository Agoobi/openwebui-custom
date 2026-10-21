# Hộp thư: Hermes ↔ Open WebUI

Dữ liệu (hội thoại, lead, trạng thái khách) nằm ở **Hermes** (skill `chatbot-tu-van`, file `inbox.py`, thư mục
`chatbot/inbox/`). Hermes **không ghi gì vào Open WebUI**: không chat, không folder, không cần API key.
Open WebUI chỉ là nơi mở trang Hộp thư (repo này) và đăng nhập.

```
trình duyệt chủ shop ── https://chat.shop.vn/static/hop-thu/index.html   (Open WebUI phục vụ file tĩnh)
        │  Authorization: Bearer <token phiên Open WebUI>
        ▼
https://bot.shop.vn/inbox/api/*   (plugin webchat của Hermes) ── GET <open_webui.url>/api/v1/auths/ ──► Open WebUI
                                                                   "token này của ai, vai trò gì?"
```

## API của Hermes

| Gọi | Trả |
| --- | --- |
| `GET /inbox/api/index` | `{ok, me, v: 2, updated_at, shop, items: [...]}` mỗi khách 1 dòng, mới nhất trước |
| `GET /inbox/api/conv?c=<conv>` | `{ok, item, messages: [...]}` thông tin khách + tối đa 500 tin / sự kiện |
| `POST /inbox/api/action` `{conv, action}` | `action`: `da_goi` (giữ Cần xử lý, ghi chú), `xong` (→ Đã xong), `mo_lai` (→ Đang chat) |

Một dòng `items`:

```json
{"conv": "web:<vid>", "kenh": "web", "status": "can_xu_ly | dang_chat | da_xong",
 "profile": {"ten": "Lan", "sdt": "0912345678", "zalo": "", "nhu_cau": "…"},
 "page": "https://…", "first_q": "…", "last_text": "…", "last_role": "user | assistant",
 "first_at": 0, "last_at": 0, "last_user_at": 0, "n": 7, "msgs": 5, "blocked": 0,
 "note": {"action": "da_goi", "t": 0, "by": "Admin"}, "events": [{"kind": "lead", "t": 0}]}
```

Một phần tử `messages`: `{"n", "t", "role": "user | assistant | event", "text"}`; sự kiện có thêm
`"kind": "lead | handoff | guard_blocked | da_goi | xong | mo_lai"` và `"data"` (tên, SĐT, lý do, khách hỏi…).
`n` tăng ở mỗi tin hoặc sự kiện: trang so `n` để biết khi nào tải lại hội thoại.

## Đăng nhập và CORS

- Trang lấy `localStorage.token` (phiên đăng nhập Open WebUI, cùng origin) và gửi kèm mọi lệnh gọi.
- Hermes hỏi `GET <open_webui.url>/api/v1/auths/` với token đó, chỉ nhận vai trò trong `open_webui.roles`
  (mặc định `admin`), nhớ kết quả 60 giây. Không nhận API key `sk-…`.
- CORS chỉ mở cho `open_webui.public_url` (origin của Open WebUI); origin khác bị 403.

## Cấu hình

- Repo này: `HERMES_INBOX_URL=https://bot.shop.vn deploy/install.sh` ghi `static/hop-thu/config.json` (`{"api": …}`).
- Hermes `chatbot/settings.json`: `open_webui.url` (Hermes gọi tới, vd `http://127.0.0.1:8080`),
  `open_webui.public_url` (vd `https://chat.shop.vn`), `open_webui.roles`.

## Kiểm lại khi nâng cấp Open WebUI

1. `src/app.html` vẫn nạp `/static/loader.js` và `/static/custom.css`; `/static` vẫn phục vụ thư mục con.
2. Sidebar vẫn có `#sidebar-search-button` nằm trong 1 hàng `div` (nút Hộp thư chèn ngay sau hàng đó).
3. `GET /api/v1/auths/` với token phiên vẫn trả `{id, name, role}`; token vẫn nằm ở `localStorage.token`.
