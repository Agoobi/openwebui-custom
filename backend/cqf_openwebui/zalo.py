"""Kenh Zalo OA: khach nhan tin cho OA -> chatbot tra loi ngay trong Zalo (tin tu van /v3.0/oa/message/cs).

Webhook: app Zalo (developers.zalo.me) goi POST /api/v1/cqf/zalo/webhook, chu ky
X-ZEvent-Signature = sha256(app_id + body + timestamp + OA Secret Key). Token OA dung CHUNG voi skill dang bai
viet-bai-zalo-oa cua Hermes (cung VPS): goi zalo_tokens.access_token cua skill do (khoa file, tu lam moi). Refresh
token Zalo chi dung 1 lan, hai noi tu giu token rieng se lam hong nhau.

Nhan vien tra loi khach trong Zalo (su kien oa_send_text khong phai tin bot vua gui) -> bot ngung voi khach do
trong N gio (cai dat), de nhan vien noi chuyen.
"""
import asyncio, hashlib, hmac, importlib.util, json, logging, re, threading, time
from pathlib import Path

import aiohttp

from . import hermes_llm

logger = logging.getLogger("cqf_openwebui.zalo")
API = "https://openapi.zalo.me"
SKILL_TOKENS = hermes_llm.HERMES_HOME / "skills/social-media/viet-bai-zalo-oa/scripts/zalo_tokens.py"
MAX_TEXT = 2000  # Zalo cat tin dai hon


class ZaloError(RuntimeError):
    pass


# ---------------------------------------------------------------- token (dung chung voi Hermes)

_mod = None


def _tokens_module():
    global _mod
    if _mod is None:
        if not SKILL_TOKENS.exists():
            raise ZaloError(f"Chưa có skill viet-bai-zalo-oa của Hermes ({SKILL_TOKENS}) để lấy token OA.")
        spec = importlib.util.spec_from_file_location("cqf_zalo_tokens", SKILL_TOKENS)
        _mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_mod)
    return _mod


def app_credentials():
    env = {**hermes_llm._dotenv(hermes_llm.HERMES_HOME / ".env"),
           **hermes_llm._dotenv(hermes_llm.HERMES_HOME / ".coquifly.env")}
    app_id, secret = env.get("ZALO_APP_ID", ""), env.get("ZALO_APP_SECRET", "")
    if not app_id or not secret:
        raise ZaloError("Hermes chưa có ZALO_APP_ID / ZALO_APP_SECRET (file .env của Hermes).")
    return app_id, secret


def access_token(oa_id):
    app_id, secret = app_credentials()
    try:
        return _tokens_module().access_token(str(oa_id), app_id=app_id, secret=secret)
    except Exception as e:  # ZaloAuthError cua skill
        raise ZaloError(f"Không lấy được token OA: {e}")


# ---------------------------------------------------------------- webhook

def verify(raw: bytes, headers, oa_secret_key: str):
    """Su kien da kiem chu ky, hoac None (sai chu ky / sai dinh dang)."""
    if not oa_secret_key:
        return None
    try:
        body = json.loads(raw)
        app_id, _ = app_credentials()
    except (ValueError, ZaloError):
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


async def send_text(oa_id, user_id, text, state=None):
    """Gui tin tu van; tra danh sach message_id (de nhan ra tin cua bot trong su kien oa_send_text)."""
    token = await asyncio.to_thread(access_token, oa_id)
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
