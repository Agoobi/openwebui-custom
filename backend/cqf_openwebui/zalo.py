"""Kenh Zalo OA: khach nhan tin cho OA -> chatbot tra loi ngay trong Zalo (tin tu van /v3.0/oa/message/cs).

Webhook: app Zalo (developers.zalo.me) goi POST /api/v1/cqf/zalo/webhook, chu ky
X-ZEvent-Signature = sha256(app_id + body + timestamp + OA Secret Key). App ID, App Secret, OA Secret Key nam trong
cai dat chatbot (trang Chatbot > Kenh Zalo OA). Token OA o <cqf>/zalo/tokens.json, khoa file khi lam moi: refresh
token Zalo chi dung 1 lan, nen cong cu khac dung cung OA (vd skill dang bai Zalo cua Hermes) phai doc chung file nay
(cung dinh dang, cung file khoa tokens.lock), khong giu ban rieng.

Nhan vien tra loi khach trong Zalo (su kien oa_send_text khong phai tin bot vua gui) -> bot ngung voi khach do
trong N gio (cai dat), de nhan vien noi chuyen.
"""
import asyncio, fcntl, hashlib, hmac, json, logging, os, re, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

import aiohttp

logger = logging.getLogger("cqf_openwebui.zalo")
API = "https://openapi.zalo.me"
OAUTH = "https://oauth.zaloapp.com/v4/oa/access_token"
REFRESH_MARGIN = 300  # lam moi truoc khi het han 5 phut
MAX_TEXT = 2000  # Zalo cat tin dai hon


class ZaloError(RuntimeError):
    pass


# ---------------------------------------------------------------- token OA (<cqf>/zalo/tokens.json, khoa file)
# Dinh dang: {"app_id": "...", "oas": {"<oa_id>": {"access_token", "refresh_token", "expires_at", "updated_at"}}}

class _Locked:
    def __init__(self, home):
        self.file = Path(home) / "zalo" / "tokens.json"

    def __enter__(self):
        self.file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = open(self.file.with_suffix(".lock"), "w")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        try:
            self.data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("oas", {})
        return self

    def save(self):
        tmp = self.file.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=2)
        tmp.replace(self.file)

    def __exit__(self, *exc):
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()


def app_credentials(z):
    if not z.get("app_id") or not z.get("app_secret"):
        raise ZaloError("Chưa nhập App ID / App Secret của app Zalo (trang Chatbot > Kênh Zalo OA).")
    return z["app_id"], z["app_secret"]


def _store(entry, data):
    entry["access_token"] = data["access_token"]
    entry["refresh_token"] = data.get("refresh_token") or entry.get("refresh_token")
    entry["expires_at"] = int(time.time()) + int(data.get("expires_in") or 3600)
    entry["updated_at"] = int(time.time())


def import_tokens(home, z, access, refresh):
    """Nap cap token lay o developers.zalo.me (API Explorer, loai OA access token). Thieu access: lam moi ngay."""
    if not z.get("oa_id") or not refresh:
        raise ZaloError("Cần OA ID và refresh token.")
    with _Locked(home) as s:
        s.data["app_id"] = z.get("app_id") or s.data.get("app_id", "")
        entry = s.data["oas"].setdefault(str(z["oa_id"]), {})
        _store(entry, {"access_token": access or "", "refresh_token": refresh, "expires_in": 3600 if access else 0})
        s.save()
    access_token(home, z, force=not access)


def access_token(home, z, force=False):
    """Access token con han; sap het han thi lam moi (giu khoa file trong luc lam moi)."""
    app_id, secret = app_credentials(z)
    with _Locked(home) as s:
        entry = s.data["oas"].get(str(z.get("oa_id")))
        if not entry or not entry.get("refresh_token"):
            raise ZaloError("Chưa có token OA: nạp access token + refresh token ở trang Chatbot > Kênh Zalo OA.")
        if not force and entry.get("access_token") and entry.get("expires_at", 0) - time.time() > REFRESH_MARGIN:
            return entry["access_token"]
        body = urllib.parse.urlencode({"refresh_token": entry["refresh_token"], "app_id": app_id,
                                       "grant_type": "refresh_token"}).encode()
        req = urllib.request.Request(OAUTH, body, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded", "secret_key": secret})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ZaloError(f"Không làm mới được token OA: {e}")
        if not data.get("access_token"):
            raise ZaloError(f"Zalo không làm mới token ({data.get('error_name') or data.get('error')}): refresh token "
                            "hết hạn (3 tháng không dùng) hoặc đã bị dùng ở nơi khác. Nạp lại token mới.")
        _store(entry, data)
        s.save()
        return entry["access_token"]


def token_info(home, z):
    with _Locked(home) as s:
        e = s.data["oas"].get(str(z.get("oa_id"))) or {}
    return {"has_token": bool(e.get("refresh_token")), "expires_at": e.get("expires_at", 0),
            "updated_at": e.get("updated_at", 0)}


# ---------------------------------------------------------------- webhook

def verify(raw: bytes, headers, z):
    """Su kien da kiem chu ky, hoac None (sai chu ky / sai dinh dang / chua cai App ID, OA Secret Key)."""
    oa_secret_key, app_id = z.get("oa_secret_key"), z.get("app_id")
    if not oa_secret_key or not app_id:
        return None
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    given = (headers.get("x-zevent-signature") or "").lower().removeprefix("mac=").strip()
    data = f"{app_id}{raw.decode('utf-8', 'replace')}{body.get('timestamp', '')}{oa_secret_key}"
    expected = hashlib.sha256(data.encode()).hexdigest()
    return body if given and hmac.compare_digest(given, expected) else None


def parse(body):
    """{"kind": "user_text" | "user_other" | "staff" | "other", "user_id", "oa_id", "msg_id", "text"}."""
    name = body.get("event_name", "")
    msg = body.get("message") or {}
    if name.startswith("user_send_"):
        return {"kind": "user_text" if name == "user_send_text" else "user_other",
                "user_id": str((body.get("sender") or {}).get("id") or body.get("user_id_by_app_id") or ""),
                "oa_id": str((body.get("recipient") or {}).get("id") or body.get("oa_id") or ""),
                "msg_id": str(msg.get("msg_id") or body.get("timestamp") or ""), "text": msg.get("text") or ""}
    if name.startswith("oa_send_"):  # OA gui: bot (qua API) hoac nhan vien (trong Zalo)
        return {"kind": "staff", "user_id": str((body.get("recipient") or {}).get("id") or ""),
                "oa_id": str((body.get("sender") or {}).get("id") or body.get("oa_id") or ""),
                "msg_id": str(msg.get("msg_id") or ""), "text": msg.get("text") or ""}
    return {"kind": "other", "name": name}


# ---------------------------------------------------------------- gui tin

def plain(md: str) -> str:
    """Markdown cua bot -> chu Zalo hien duoc (Zalo khong hien Markdown)."""
    out = []
    for line in md.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if re.fullmatch(r"\|?\s*:?-{2,}.*", s):
            continue  # dong ke cua bang
        if s.startswith("|"):
            s = " – ".join(c.strip() for c in s.strip("|").split("|") if c.strip())
        s = re.sub(r"^#{1,6}\s+", "", s)
        s = re.sub(r"^[-*+]\s+", "• ", s)
        s = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", s)
        out.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def chunks(text, limit=MAX_TEXT):
    parts, cur = [], ""
    for para in text.split("\n\n"):
        if cur and len(cur) + 2 + len(para) > limit:
            parts.append(cur)
            cur = ""
        cur = f"{cur}\n\n{para}".strip()
        while len(cur) > limit:
            parts.append(cur[:limit])
            cur = cur[limit:]
    return parts + ([cur] if cur else [])


async def send_text(home, z, user_id, text, state=None):
    """Gui tin tu van; tra danh sach message_id (de nhan ra tin cua bot trong su kien oa_send_text)."""
    token = await asyncio.to_thread(access_token, home, z)
    parts = chunks(plain(text))
    if state:
        state.sending(user_id, parts)
    ids = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as http:
        for part in parts:
            body = {"recipient": {"user_id": str(user_id)}, "message": {"text": part}}
            async with http.post(f"{API}/v3.0/oa/message/cs", json=body, headers={"access_token": token}) as r:
                data = await r.json(content_type=None)
            if data.get("error"):
                raise ZaloError(f"Zalo từ chối gửi tin ({data.get('error')}: {data.get('message')})")
            ids.append(str((data.get("data") or {}).get("message_id") or ""))
    return ids


# ---------------------------------------------------------------- trang thai: tin da xu ly, tin bot gui, nhan vien tiep

class ZaloState:
    """<cqf>/zalo_state.json: tin da xu ly (chong Zalo gui lai), id tin bot gui, khach dang do nhan vien tiep."""

    def __init__(self, home: Path):
        self.file = Path(home) / "zalo_state.json"
        self.lock = threading.Lock()

    def _load(self):
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"seen": {}, "sent": {}, "recent": {}, "staff": {}, "last_event": 0}

    def _save(self, d):
        now = time.time()
        d["seen"] = {k: t for k, t in d["seen"].items() if t > now - 86400}
        d["sent"] = {k: t for k, t in d["sent"].items() if t > now - 86400}
        d["recent"] = {u: [x for x in v if x[1] > now - 300] for u, v in d.get("recent", {}).items()}
        d["recent"] = {u: v for u, v in d["recent"].items() if v}
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(self.file)

    def first_time(self, msg_id):
        """True lan dau thay tin nay (Zalo gui lai su kien khi tuong minh chua nhan)."""
        with self.lock:
            d = self._load()
            d["last_event"] = time.time()
            if not msg_id or msg_id in d["seen"]:
                self._save(d)
                return not msg_id
            d["seen"][msg_id] = time.time()
            self._save(d)
            return True

    def sending(self, user_id, texts):
        """Ghi truoc khi gui: su kien oa_send_text cua chinh tin nay co the den truoc khi API tra message_id."""
        with self.lock:
            d = self._load()
            d.setdefault("recent", {}).setdefault(str(user_id), []).extend([t[:200], time.time()] for t in texts)
            self._save(d)

    def mark_sent(self, ids):
        with self.lock:
            d = self._load()
            d["sent"].update({i: time.time() for i in ids if i})
            self._save(d)

    def is_bot_message(self, msg_id, user_id, text):
        with self.lock:
            d = self._load()
        return msg_id in d["sent"] or any(t == (text or "")[:200] for t, _ in d.get("recent", {}).get(str(user_id), []))

    def staff_replied(self, user_id):
        with self.lock:
            d = self._load()
            d["staff"][str(user_id)] = time.time()
            self._save(d)

    def staff_active(self, user_id, hours):
        with self.lock:
            t = self._load()["staff"].get(str(user_id), 0)
        return hours > 0 and t > time.time() - hours * 3600

    def last_event(self):
        with self.lock:
            return self._load().get("last_event", 0)
