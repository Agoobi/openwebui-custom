# openwebui-custom

Chatbot tư vấn trên website, quản lý hoàn toàn trong **Open WebUI**: chủ shop bật/tắt, sửa thông tin, nạp kiến
thức, xem khách và lead ngay trong Open WebUI. Không cần cài gì bên Hermes; chatbot gọi thẳng LLM nên khách website
không chạm được tới công cụ của trợ lý. Không fork Open WebUI: thêm một gói Python nhỏ (`backend/cqf_openwebui`) và
vài trang tĩnh.

Sidebar Open WebUI có thêm 5 mục (dưới Search), mở ngay trong vùng nội dung, sidebar giữ nguyên:

| Mục | Làm gì |
| --- | --- |
| **Hộp thư** (kèm số khách cần xử lý) | Danh sách khách (Tất cả / Cần xử lý / Đang chat / Đã xong, lọc kênh, tìm, mới nhất / chờ lâu nhất), hội thoại, thẻ sự kiện (để lại thông tin, cần nhân viên, bot không trả lời được), thông tin khách, nút Xong / Mở lại. |
| **Chatbot** | Bật/tắt, mã nhúng (1 dòng script), thông tin shop, **cách tư vấn** (vai trò: sơ bộ rồi chuyển sale / chi tiết; độ dài; khi nào xin liên hệ, chỉ 1 lần; câu hỏi tìm hiểu nhu cầu; link tải catalogue; dặn thêm), khung chat (tiêu đề, lời chào, màu), website được gắn, **số lần tra kiến thức tối thiểu** (mặc định 4), xin khách gì khi không có câu trả lời, LLM (nhà cung cấp: dùng LLM của Hermes trên cùng VPS / Google Gemini / OpenAI / API chuẩn OpenAI khác; model chọn từ danh sách; key; thử kết nối), thử chatbot ngay trên trang. |
| **Kênh Zalo OA** (trên trang Chatbot) | Khách nhắn Zalo OA, bot trả lời ngay trong Zalo (cùng kiến thức, cách tư vấn; không bảng / Markdown). Nhân viên trả lời khách trong Zalo thì bot im với khách đó N giờ. Tin vào Hộp thư, kênh "Zalo OA". Webhook `POST /api/v1/cqf/zalo/webhook` (kiểm chữ ký bằng OA Secret Key). App ID, App Secret, OA Secret Key nhập trên trang Chatbot; token OA nạp ở đó và lưu `cqf/zalo/tokens.json`. Công cụ khác dùng cùng OA (vd skill `viet-bai-zalo-oa` của Hermes) phải dùng chung file này, ví dụ symlink `~/.hermes/zalo` → `cqf/zalo` (refresh token Zalo chỉ dùng 1 lần). |
| **Thử chatbot** | Chat với bot như khách (cùng cài đặt, kiến thức đang bật; chạy cả khi chatbot đang tắt trên website). Bên phải là "Bot đã làm gì" cho từng câu trả lời: các câu tra tự động, đoạn tài liệu đưa cho bot, công cụ bot gọi thêm và kết quả, số liệu bị chặn. Tin thử lưu riêng trên server (`cqf/test/`, theo từng quản trị viên), không vào Hộp thư; nút **Lịch sử** mở lại các cuộc thử trước, máy / trình duyệt nào cũng thấy. |
| **Kiến thức** | Kiểu Obsidian: tải file Word / Excel / CSV / PDF có chữ / TXT / MD lên (kéo thả được) thành ghi chú, xem / sửa Markdown, `[[liên kết]]` giữa ghi chú, mục lục, ghi chú trỏ tới, bật/tắt từng ghi chú, cảnh báo khi số liệu sửa tay khác file gốc, **thử tìm như bot**. |
| **Lịch đăng** | Lịch bài WordPress và Zalo OA: xem **Tuần / Tháng / Danh sách**, chọn **múi giờ** xem, lọc Sắp đăng / Đã đăng / Lỗi, cột **Chưa lên lịch** (kéo vào lịch để hẹn), bấm ô trống để hẹn bài vào giờ đó, kéo bài đã hẹn để đổi giờ. Bấm 1 bài: xem trước như trên web, ảnh bìa, đổi giờ, **khung giờ trống kế tiếp**, **Đăng thật / Lưu nháp trên WordPress**, huỷ lịch (bài về Chưa lên lịch), thử lại khi lỗi, lịch sử. **Cài đặt**: kết nối nhiều site WordPress (Application Password, kiểm tra kết nối, mã hoá khi lưu), múi giờ, chế độ mặc định, site mặc định, **khung giờ đăng** hằng tuần. **Quy tắc** viết sẵn trên trang. Mỗi người dùng Open WebUI có lịch, site, cài đặt riêng. |

## Lịch đăng

- Bài nằm trong Lịch đăng tới giờ hẹn; máy chủ (luồng nền trong Open WebUI, kiểm mỗi 10 giây) gửi lên WordPress qua REST
  API bằng Application Password: tải ảnh bìa và ảnh trong bài, gắn chuyên mục (chỉ chuyên mục có sẵn) và thẻ (tạo nếu
  chưa có), trạng thái `publish` (Đăng thật) hoặc `draft` (Lưu nháp). Không cần plugin hay cron trên hosting.
- Lỗi mạng / tường lửa / site bận: thử lại sau 1, 2, 5, 10 phút, tới 3 giờ sau giờ hẹn; lần thử lại tìm bài theo slug nên
  không tạo bài trùng. Sai mật khẩu, thiếu quyền, chuyên mục không có: báo Lỗi ngay. Tường lửa hosting chặn IP máy chủ:
  trang báo rõ IP cần cho phép.
- Mọi thời điểm lưu theo UTC; giờ nhập và hiển thị theo múi giờ chọn.
- **Zalo OA** cũng là một nơi đăng: OA đã kết nối ở trang Chatbot → Kênh Zalo OA (dùng chung kho token
  `cqf/zalo/tokens.json` và khoá file, vì refresh token Zalo chỉ dùng được 1 lần) được thêm trong Lịch đăng → Cài đặt →
  Kết nối. Tới giờ máy chủ tạo bài (article) trên OA: **Hiện ngay** (`show`) hoặc **Tạo bài ẩn** (`hide`, chủ OA tự
  bật). Không gửi broadcast. Bài Zalo chỉ có chữ và ảnh; Lịch đăng kiểm khi hẹn: phải có ảnh bìa, tiêu đề ≤ 150, mô tả
  ≤ 300 ký tự. Zalo tải ảnh qua link công khai có chữ ký, hết hạn sau 6 giờ, trên `WEBUI_URL` (phải là https công
  khai); ảnh > 1 MB được thu nhỏ. Mã chờ của Zalo (`article/create`) được giữ để lần thử lại hỏi tiếp (`verify`,
  kể cả khi Zalo trả `-214` đang xử lý ảnh) thay vì tạo bài thứ hai.
- Đồng bộ 2 chiều với **Lịch** của Open WebUI: lịch "Lịch đăng bài" (mỗi bài 1 sự kiện, màu theo trạng thái) và
  "Khung giờ đăng" (sự kiện lặp hằng tuần). Kéo sự kiện sang giờ khác = đổi giờ đăng; xoá sự kiện = huỷ lịch.
- Agent (Hermes cùng máy, skill `viet-bai-website-wordpress` trong
  [skills-hubs](https://github.com/Agoobi/skills-hubs)) gọi API bằng token trong `cqf/lich/agent.json`, làm việc cho 1
  người dùng (quản trị viên đổi được trên trang Cài đặt). Agent tạo / sửa bài, xem trước, hẹn giờ khi user đồng ý; không
  sửa site hay cài đặt.
- Dữ liệu: `<DATA_DIR>/cqf/lich/` (`lich.db`, `covers/`, `secret.key`, `agent.json`), quyền 600 / 700.
- Test: `cd backend && python -m pytest -q tests` (cần fastapi, httpx, cryptography, pytest; test đồng bộ lịch chạy
  trên bản sao `/opt/open-webui/data/webui.db` nếu máy có Open WebUI).

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
dán mã nhúng vào website. **Lịch đăng** → Cài đặt: kết nối site WordPress (Application Password).

Hermes trả lời trong Open WebUI qua API server, mà Hermes mặc định coi API server là "chữ thường, không Markdown" (bảng,
ảnh, chữ đậm bị bỏ). Chạy thêm một lần để Hermes dùng Markdown trong Open WebUI (chỉ đổi kênh API server):

```bash
sudo /opt/openwebui-custom/deploy/hermes-openwebui.sh            # mặc định HERMES_HOME=/root/.hermes
```

Agent viết bài và hẹn giờ qua Lịch đăng: skill `viet-bai-website-wordpress` và `viet-bai-zalo-oa` (bản 0.2.0) trong
[skills-hubs](https://github.com/Agoobi/skills-hubs).

## API (`/api/v1/cqf`)

- Công khai (khung chat, kiểm Origin trong danh sách website): `GET /webchat/widget.js`, `POST /webchat/chat`.
- Quản trị (đăng nhập Open WebUI, vai trò admin, dùng `get_admin_user` của Open WebUI): `/settings`,
  `/settings/test`, `/kb*`, `/inbox/*`, `/status`, `/test/stream` (Thử chatbot: như `/webchat/stream` kèm sự kiện `trace`), `/test/sessions`, `/test/session`.
- Lịch đăng (đăng nhập Open WebUI, mọi người dùng đã duyệt; hoặc header `X-Lich-Agent-Token`): `/lich/*`, xem
  `backend/cqf_openwebui/lich/router.py`.

## Phiên bản

Đã kiểm với **Open WebUI 0.11.4**, `UVICORN_WORKERS=1` (mặc định). Nâng cấp thì kiểm lại:

1. `src/app.html` vẫn nạp `/static/loader.js`, `/static/custom.css`; `/static` phục vụ thư mục con.
2. `open-webui serve` vẫn chỉ đặt `FROM_INIT_PY`, `WEBUI_SECRET_KEY` rồi `uvicorn.run('open_webui.main:app')`.
3. Sidebar còn `#sidebar-search-button` trong 1 hàng `div`; token phiên vẫn ở `localStorage.token`.
4. `open_webui.utils.auth.get_admin_user`, `open_webui.env.DATA_DIR` còn nguyên.

## Giấy phép Open WebUI

Giấy phép Open WebUI cấm đổi, ẩn tên và logo "Open WebUI" khi một bản có quá 50 người dùng trong 30 ngày (trừ bản
enterprise). Repo này không đụng tới thương hiệu.
