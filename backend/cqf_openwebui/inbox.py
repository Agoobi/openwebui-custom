"""Hop thu chatbot: Hermes tu luu hoi thoai + lead cua khach website va phuc vu trang "Hop thu"
(repo openwebui-custom, static/hop-thu) qua API cua plugin webchat:

    GET  /inbox/api/index            danh sach khach (1 dong / khach, moi nhat truoc)
    GET  /inbox/api/conv?c=<conv>    1 khach: thong tin + tin nhan + su kien
    POST /inbox/api/action           {"conv", "action": "da_goi" | "xong" | "mo_lai"}

KHONG ghi gi vao Open WebUI (khong chat, khong folder). Open WebUI chi la noi mo trang va dang nhap: trang gui token
dang nhap Open WebUI, webchat hoi Open WebUI /api/v1/auths/ xem token cua ai (xem webchat/adapter.py).

Du lieu: $CHATBOT_HOME/inbox/index.json (trang thai tung khach) va inbox/<id>.jsonl (tin nhan, su kien), quyen 600.
Chi dung thu vien chuan; setup.py chep file nay vao 2 plugin, get_inbox() bao dam ca tien trinh dung 1 ban.
"""
import hashlib, json, os, sys, threading, time, types
from pathlib import Path

STATUS = ("can_xu_ly", "dang_chat", "da_xong")
ACTIONS = {"da_goi": "can_xu_ly", "xong": "da_xong", "mo_lai": "dang_chat"}  # nut -> trang thai moi
ATTENTION = ("lead", "handoff", "guard_blocked")  # su kien dua khach vao "Can xu ly"
PROFILE = ("ten", "sdt", "zalo", "email", "cong_ty", "dia_chi", "thoi_gian", "nhu_cau")
INDEX_MAX = 1000  # so khach toi da tra ve trong danh sach (moi nhat)


def get_inbox(home: Path, settings: dict = None):
    """1 ban Inbox cho ca tien trinh (2 plugin import 2 ban sao cua module nay)."""
    holder = sys.modules.setdefault("_chatbot_inbox", types.ModuleType("_chatbot_inbox"))
    with holder.__dict__.setdefault("lock", threading.Lock()):  # dict.setdefault la nguyen tu
        box = getattr(holder, "boxes", {}).get(str(home))
        if box is None:
            holder.boxes = {**getattr(holder, "boxes", {}), str(home): Inbox(home, settings or {})}
            box = holder.boxes[str(home)]
        return box


def _now():
    return int(time.time())


class Inbox:
    def __init__(self, home: Path, settings: dict):
        self.dir = Path(home) / "inbox"
        self.shop = (settings.get("business") or {}).get("ten") or ""
        self.lock = threading.Lock()
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)  # SDT khach
        except OSError:
            pass

    # ---------------------------------------------------------------- ghi (goi tu plugin, khong bao gio raise)

    def message(self, conv, role, text, page=None):
        self._safe(self._message, conv, role, str(text or ""), page)

    def event(self, conv, kind, data):
        self._safe(self._event, conv, kind, dict(data or {}))

    def action(self, conv, action, by=""):
        """Nut tren trang Hop thu. Tra False neu khong co khach / nut khong hop le."""
        if action not in ACTIONS:
            return False
        with self.lock:
            idx = self._load()
            if conv not in idx:
                return False
            st = idx[conv]
            st["status"] = ACTIONS[action]
            st["note"] = {"action": action, "t": _now(), "by": by}
            self._append(idx, conv, st, {"role": "event", "kind": action, "data": {"by": by}})
            self._save(idx)
        return True

    def _safe(self, fn, *args):
        try:
            with self.lock:
                fn(*args)
        except Exception as e:  # hop thu loi khong duoc lam hong cuoc tro chuyen
            import logging
            logging.getLogger("chatbot_inbox").warning("[inbox] khong ghi duoc: %s", e)

    def _entry(self, idx, conv, t):
        return idx.setdefault(conv, {"id": hashlib.sha1(conv.encode()).hexdigest()[:16], "kenh": conv.split(":")[0],
                                     "status": "dang_chat", "first_at": t, "n": 0, "msgs": 0, "blocked": 0,
                                     "profile": {}, "events": []})

    def _message(self, conv, role, text, page):
        idx, t = self._load(), _now()
        st = self._entry(idx, conv, t)
        st["msgs"] += 1
        st["last_at"] = t
        st["last_text"], st["last_role"] = text[:160], role
        if page and not st.get("page"):
            st["page"] = str(page)[:300]
        if role == "user":
            st["last_user_at"] = t
            st.setdefault("first_q", text[:80])
            if st["status"] == "da_xong":
                st["status"] = "dang_chat"  # khach quay lai: mo lai
        self._append(idx, conv, st, {"role": role, "text": text})
        self._save(idx)

    def _event(self, conv, kind, data):
        idx, t = self._load(), _now()
        st = self._entry(idx, conv, t)
        for k in PROFILE:
            if data.get(k):
                st["profile"][k] = str(data[k])[:200]
        if not data.get("nhu_cau") and (data.get("tom_tat") or data.get("ly_do")) and kind != "guard_blocked":
            st["profile"]["nhu_cau"] = str(data.get("tom_tat") or data.get("ly_do"))[:200]
        if kind == "guard_blocked":
            st["blocked"] += 1
        if kind in ATTENTION:
            st["status"] = "can_xu_ly"
            st.pop("note", None)
        clean = {k: (v if isinstance(v, (str, int, float, list)) else str(v)) for k, v in data.items()}
        self._append(idx, conv, st, {"role": "event", "kind": kind, "data": clean})
        self._save(idx)

    def _append(self, idx, conv, st, rec):
        st["n"] += 1
        rec = {"n": st["n"], "t": _now(), **rec}
        if rec["role"] == "event":
            st["events"] = (st["events"] + [{"kind": rec["kind"], "t": rec["t"]}])[-20:]
        fd = os.open(self.dir / f"{st['id']}.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---------------------------------------------------------------- doc (API)

    def index(self):
        with self.lock:
            idx = self._load()
        rows = sorted(idx.items(), key=lambda kv: -(kv[1].get("last_at") or kv[1].get("first_at") or 0))[:INDEX_MAX]
        return {"v": 2, "updated_at": max([v.get("last_at") or 0 for v in idx.values()] + [0]), "shop": self.shop,
                "items": [{"conv": k, **{x: v.get(x) for x in v if x != "id"}} for k, v in rows]}

    def conversation(self, conv):
        with self.lock:
            st = self._load().get(conv)
        if not st:
            return None
        f = self.dir / f"{st['id']}.jsonl"
        msgs = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()] if f.exists() else []
        return {"item": {"conv": conv, **{x: st[x] for x in st if x != "id"}}, "messages": msgs[-500:]}

    # ---------------------------------------------------------------- file

    def _load(self):
        f = self.dir / "index.json"
        try:
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except ValueError:
            return {}

    def _save(self, idx):
        tmp = self.dir / "index.json.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False)
        tmp.replace(self.dir / "index.json")
