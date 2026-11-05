"""Lich dang: settings, limits and the rules shown to people.

Every rule is written once here and reused by the API errors, the page and the agent skill, so what the UI says is
what the code does. Data lives in <DATA_DIR of Open WebUI>/cqf/lich/ (mode 700); LICH_HOME overrides it (tests).
"""

import json
import os
import secrets
import socket
from pathlib import Path


def _home() -> Path:
    if os.environ.get("LICH_HOME"):
        path = Path(os.environ["LICH_HOME"])
    else:
        from ..store import root  # inside Open WebUI: <DATA_DIR>/cqf

        path = root() / "lich"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _owui_db() -> Path | None:
    """The Open WebUI SQLite database, for the calendar mirror. None when Open WebUI runs on another database."""
    if os.environ.get("OWUI_DB"):
        return Path(os.environ["OWUI_DB"])
    try:
        from open_webui.env import DATA_DIR, DATABASE_URL
    except ImportError:
        return None
    if DATABASE_URL and not DATABASE_URL.startswith("sqlite"):
        return None
    return Path(DATA_DIR) / "webui.db"


def _private_file(path: Path, make) -> str:
    if not path.exists():
        path.write_text(make())
        os.chmod(path, 0o600)
    return path.read_text().strip()


def _server_ip() -> str:
    """The address this machine uses to reach the internet (no packet is sent), shown in firewall hints."""
    if os.environ.get("LICH_SERVER_IP"):
        return os.environ["LICH_SERVER_IP"]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("1.1.1.1", 80))
            return probe.getsockname()[0]
    except OSError:
        return ""


DATA_DIR = _home()
DB_PATH = DATA_DIR / "lich.db"
COVER_DIR = DATA_DIR / "covers"
OWUI_DB = _owui_db()


def _fernet_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


SECRET_KEY = os.environ.get("LICH_SECRET_KEY") or _private_file(DATA_DIR / "secret.key", _fernet_key)

# The agent (Hermes on the same machine) calls the API with this token, for one Open WebUI user.
# agent.json: {"token": "...", "user_id": "<Open WebUI user id>", "name": "Agent"}; the token is made on first start,
# user_id is the first admin until someone presses "Agent làm việc cho tôi" in Cài đặt.
AGENT_FILE = DATA_DIR / "agent.json"


def agent() -> dict:
    data = {}
    if AGENT_FILE.exists():
        try:
            data = json.loads(AGENT_FILE.read_text())
        except ValueError:
            data = {}
    changed = False
    if not data.get("token"):
        data["token"] = secrets.token_urlsafe(32)
        changed = True
    if not data.get("user_id"):
        data["user_id"] = _first_admin()
        changed = changed or bool(data["user_id"])
    if changed:
        save_agent(data)
    data.setdefault("name", "Agent")
    return data


def _first_admin() -> str | None:
    if OWUI_DB is None or not OWUI_DB.exists():
        return None
    import sqlite3

    try:
        with sqlite3.connect(f"file:{OWUI_DB}?mode=ro", uri=True, timeout=5) as conn:
            row = conn.execute("SELECT id FROM user WHERE role='admin' ORDER BY created_at LIMIT 1").fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def save_agent(data: dict) -> None:
    AGENT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.chmod(AGENT_FILE, 0o600)


SERVER_PUBLIC_IP = _server_ip()
# Public https address of this Open WebUI (WEBUI_URL). Zalo downloads a post's images from here while it processes
# the article, through signed links that expire (PUBLIC_LINK_SECONDS).
PUBLIC_URL = (os.environ.get("LICH_PUBLIC_URL") or os.environ.get("WEBUI_URL") or "").rstrip("/")
PUBLIC_LINK_SECONDS = 6 * 3600
BASE_PATH = "/#lich-dang"
USER_AGENT = "LichDang/1.0 (+openwebui-custom; WordPress REST scheduler)"

MIN_LEAD_SECONDS = 120
WORKER_TICK_SECONDS = 10
MIRROR_EVERY_SECONDS = 20
HTTP_TIMEOUT_SECONDS = 40
# After a failed send: wait this long before the next try (the last value repeats).
RETRY_DELAYS_SECONDS = (60, 120, 300, 600)
# Past this many seconds after the due time a post that still fails is marked as an error.
GIVE_UP_AFTER_SECONDS = 3 * 3600
SLOT_GAP_SECONDS = 30 * 60
SLOT_LOOKAHEAD_DAYS = 60
MAX_COVER_BYTES = 8 * 1024 * 1024
MAX_HTML_BYTES = 2 * 1024 * 1024

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
DEFAULT_MODE = "publish"
DEFAULT_SETTINGS = {
    "timezone": DEFAULT_TIMEZONE,
    "default_mode": DEFAULT_MODE,
    "default_site_id": None,
    "slots": [{"days": [1, 3, 5], "time": "08:00"}],
}

STATES = ("unscheduled", "scheduled", "sending", "sent", "failed")
MODES = ("publish", "draft")
STATE_LABELS = {
    "unscheduled": "Chưa lên lịch",
    "scheduled": "Sắp đăng",
    "sending": "Đang gửi",
    "sent": "Đã đăng",
    "failed": "Lỗi",
}
MODE_LABELS = {"publish": "Đăng thật", "draft": "Lưu nháp trên WordPress"}
KINDS = ("wordpress", "zalo_oa")
KIND_LABELS = {"wordpress": "WordPress", "zalo_oa": "Zalo OA"}
MODE_LABELS_BY_KIND = {
    "wordpress": MODE_LABELS,
    "zalo_oa": {"publish": "Hiện ngay trên Zalo OA", "draft": "Tạo bài ẩn trên Zalo OA"},
}
ZALO_LIMITS = {"title": 150, "excerpt": 300}

# Colours of the events in the Open WebUI calendar, one per state.
STATE_COLORS = {
    "scheduled": "#d97706",
    "sending": "#2563eb",
    "sent": "#16a34a",
    "failed": "#dc2626",
}

RULES = [
    {
        "key": "hold",
        "title": "Bài được giữ ở đây tới giờ đăng",
        "text": "Bài nằm trong Lịch đăng, đúng giờ hẹn máy chủ mới gửi lên WordPress qua REST API. "
        "Sửa bài trước giờ đó thì bài đi nội dung mới.",
    },
    {
        "key": "mode",
        "title": "Đăng thật hay lưu nháp",
        "text": "Đăng thật: tới giờ bài hiện ngay trên site. Lưu nháp: tới giờ bài vào WordPress ở dạng nháp, "
        "bạn tự bấm Đăng trong WordPress. Chọn riêng cho từng bài; bài mới lấy theo Cài đặt.",
    },
    {
        "key": "lead",
        "title": "Hẹn trước ít nhất 2 phút",
        "text": "Giờ hẹn phải sau lúc này ít nhất 2 phút. Muốn đăng sớm nhất có thể thì chọn giờ 2 phút tới.",
    },
    {
        "key": "agent",
        "title": "Agent chỉ hẹn khi bạn đã duyệt",
        "text": "Agent viết bài và cho xem trước trong chat. Agent chỉ lên lịch khi bạn đồng ý trong chat, "
        "không tự đăng ngay, không sửa kết nối WordPress hay Cài đặt.",
    },
    {
        "key": "retry",
        "title": "Lỗi mạng thì tự thử lại",
        "text": "Không gửi được (mạng, site bận, tường lửa) thì máy chủ thử lại sau 1, 2, 5, 10 phút, tới 3 giờ "
        "sau giờ hẹn. Sai mật khẩu hay thiếu quyền thì báo Lỗi ngay. Thử lại không tạo bài trùng.",
    },
    {
        "key": "cancel",
        "title": "Huỷ lịch không mất bài",
        "text": "Huỷ lịch thì bài về cột Chưa lên lịch, nội dung giữ nguyên, hẹn lại lúc nào cũng được.",
    },
    {
        "key": "sent",
        "title": "Đã đăng thì sửa trong WordPress",
        "text": "Bài đã gửi lên WordPress thì không sửa ở đây nữa; mở bài trong WordPress để sửa.",
    },
    {
        "key": "owui",
        "title": "Lịch của Open WebUI đi theo",
        "text": "Bài hẹn cũng hiện trong Lịch của Open WebUI (lịch \"Lịch đăng bài\"). Kéo sang giờ khác ở đó "
        "thì giờ đăng đổi theo; xoá sự kiện ở đó là huỷ lịch.",
    },
    {
        "key": "time",
        "title": "Giờ theo múi giờ bạn chọn",
        "text": "Giờ hiển thị và giờ bạn nhập theo múi giờ trong Cài đặt (hoặc múi giờ đang xem). Bên dưới "
        "máy chủ lưu theo UTC nên đổi múi giờ không làm lệch giờ đăng.",
    },
    {
        "key": "zalo",
        "title": "Zalo OA",
        "text": "Tới giờ máy chủ tạo bài trên Zalo OA: Hiện ngay, hoặc Tạo bài ẩn để chủ OA tự bật hiển thị. Lịch đăng "
        "không gửi bài cho người quan tâm (broadcast): chủ OA tự gửi trên oa.zalo.me. Bài Zalo chỉ có chữ và ảnh, "
        "không chữ đậm, không link bấm được; cần ảnh bìa, tiêu đề tối đa 150 ký tự, mô tả tối đa 300 ký tự; ảnh lớn "
        "hơn 1 MB được thu nhỏ. OA lấy từ kết nối Zalo của trang Chatbot.",
    },
    {
        "key": "password",
        "title": "Application password",
        "text": "Kết nối dùng application password của WordPress (Người dùng → Hồ sơ → Application Passwords), "
        "không dùng mật khẩu đăng nhập. Mật khẩu được mã hoá khi lưu và không bao giờ hiện lại.",
    },
]
RULE_TEXT = {rule["key"]: rule["text"] for rule in RULES}
