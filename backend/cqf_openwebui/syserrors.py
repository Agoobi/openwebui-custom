"""Loi he thong cua bot (LLM tu choi / mat ket noi, gui Zalo that bai): hien bang do tren Hop thu cho quan tri vien sua.

Du lieu: $home/loi.json (50 loi gan nhat), quyen 600. Bam "Đã xử lý" tren Hop thu -> an cac loi den thoi diem do.
"""
import json, os, threading, time
from pathlib import Path

KEEP = 50


class SysErrors:
    def __init__(self, home: Path):
        self.f = Path(home) / "loi.json"
        self.lock = threading.Lock()

    def add(self, conv, loi, khach_hoi=""):
        with self.lock:
            data = self._load()
            data["items"] = (data["items"] + [{"t": int(time.time()), "conv": conv, "loi": str(loi)[:500],
                                               "khach_hoi": str(khach_hoi)[:300]}])[-KEEP:]
            self._save(data)

    def active(self):
        """Loi chua bam "Đã xử lý", moi nhat truoc."""
        with self.lock:
            data = self._load()
        return [e for e in reversed(data["items"]) if e["t"] > data["cleared_at"]]

    def clear(self):
        with self.lock:
            data = self._load()
            data["cleared_at"] = int(time.time())
            self._save(data)

    def _load(self):
        try:
            data = json.loads(self.f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {"items": list(data.get("items") or []), "cleared_at": int(data.get("cleared_at") or 0)}

    def _save(self, data):
        tmp = self.f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.f)
