"""Lich su trang "Thu chatbot": moi quan tri vien 1 thu muc, moi cuoc thu 1 file JSON (cau hoi, cau tra loi, trace).

<cqf>/test/log/<user_id>/<sid>.json   {"sid", "title", "created_at", "updated_at", "turns": [{role, text, trace?}]}
Luu tren server nen mo tren may / trinh duyet nao cung thay. Ngu canh hoi thoai cho bot van do Inbox (test/inbox) giu.
"""
import json, os, re, threading, time
from pathlib import Path

SID = re.compile(r"[A-Za-z0-9_-]{8,64}")
USER = re.compile(r"[A-Za-z0-9_.@-]{1,128}")
MAX_SESSIONS = 200  # moi quan tri vien: giu 200 cuoc thu gan nhat


class TestLog:
    def __init__(self, home: Path):
        self.dir = Path(home) / "test" / "log"
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o700)
        self.lock = threading.Lock()

    def _udir(self, user_id):
        if not USER.fullmatch(str(user_id)):
            raise ValueError("user")
        d = self.dir / str(user_id)
        d.mkdir(mode=0o700, exist_ok=True)
        return d

    def _file(self, user_id, sid):
        if not SID.fullmatch(sid or ""):
            raise ValueError("sid")
        return self._udir(user_id) / f"{sid}.json"

    def _read(self, f):
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def add(self, user_id, sid, question, answer, trace):
        """Ghi 1 luot (cau hoi + cau tra loi) vao cuoi cuoc thu."""
        f = self._file(user_id, sid)
        now = int(time.time())
        with self.lock:
            data = self._read(f) or {"sid": sid, "title": question[:80], "created_at": now, "turns": []}
            data["turns"] += [{"role": "user", "text": question}, {"role": "bot", "text": answer, "trace": trace}]
            data["updated_at"] = now
            tmp = f.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            tmp.replace(f)
            self._prune(f.parent)

    def _prune(self, d):
        files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[MAX_SESSIONS:]:
            old.unlink(missing_ok=True)

    def sessions(self, user_id):
        out = []
        for f in self._udir(user_id).glob("*.json"):
            data = self._read(f)
            if data:
                out.append({"sid": data["sid"], "title": data.get("title") or "", "updated_at": data.get("updated_at", 0),
                            "turns": len(data.get("turns", [])) // 2})
        return sorted(out, key=lambda x: -x["updated_at"])

    def get(self, user_id, sid):
        f = self._file(user_id, sid)
        return self._read(f) if f.exists() else None

    def delete(self, user_id, sid):
        with self.lock:
            self._file(user_id, sid).unlink(missing_ok=True)
