"""Cai dat chatbot website, luu o <DATA_DIR cua Open WebUI>/cqf/settings.json (quyen 600).

Chu shop sua tren trang "Chatbot" cua Open WebUI; doi la co hieu luc ngay (moi lan doc deu lay ban moi nhat).
"""
import copy, json, os, threading
from pathlib import Path

DEFAULTS = {
    "enabled": False,  # tat: widget.js khong hien gi, /chat tra 503
    "business": {"ten": "", "hotline": "", "zalo": "", "email": "", "gio_lam_viec": "", "website": "", "dia_chi": ""},
    "widget": {"title": "Tư vấn", "color": "#0e7466",
               "greeting": "Xin chào! Em có thể giúp gì cho anh/chị ạ?"},
    "allowed_origins": [],  # website duoc gan khung chat (du ca www)
    "thu_thap_khach": ["ten", "sdt"],  # bot xin khach gi khi tai lieu khong co cau tra loi
    "fallback_text": "",
    "min_searches": 4,  # so lan tra kien thuc toi thieu moi cau tra loi (code tu tra, khong phu thuoc model)
    "max_passages": 6,  # so doan tai lieu toi da dua vao 1 lan tra
    "max_tool_rounds": 4,  # so vong model duoc goi tool them
    "llm": {"base_url": "", "api_key": "", "model": "", "temperature": 0.3},
}
SECRET = ("llm", "api_key")


def root() -> Path:
    from open_webui.env import DATA_DIR  # chi import khi chay trong Open WebUI

    d = Path(DATA_DIR) / "cqf"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


_lock = threading.Lock()


def load(home: Path = None) -> dict:
    f = (home or root()) / "settings.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        data = {}
    return _merge(DEFAULTS, data)


def save(patch: dict, home: Path = None) -> dict:
    """Ghi de cac khoa trong patch (giu khoa khac). api_key rong = giu key cu."""
    home = home or root()
    with _lock:
        cur = load(home)
        new = _merge(cur, patch)
        if not ((patch.get("llm") or {}).get("api_key") or "").strip():
            new["llm"]["api_key"] = cur["llm"]["api_key"]
        new["min_searches"] = max(1, min(10, int(new.get("min_searches") or 4)))
        new["max_passages"] = max(2, min(12, int(new.get("max_passages") or 6)))
        new["max_tool_rounds"] = max(0, min(8, int(new.get("max_tool_rounds") or 0)))
        new["allowed_origins"] = sorted({o.strip().rstrip("/") for o in new.get("allowed_origins") or []
                                         if str(o).strip().startswith(("https://", "http://"))})
        tmp = home / "settings.json.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(new, fh, ensure_ascii=False, indent=2)
        tmp.replace(home / "settings.json")
        return new


def public(s: dict) -> dict:
    """Ban gui cho trang Chatbot: khong lo api_key, chi bao da co hay chua."""
    out = copy.deepcopy(s)
    key = out["llm"].pop("api_key", "")
    out["llm"]["has_key"] = bool(key)
    return out
