"""Săn lead: validation, dedupe, scoring and the Apify key. The router only maps HTTP to these functions.

The agent (skill san-lead-b2b) sends opportunities and people it extracted; everything is checked here, so a sloppy
extraction is refused with a reason the agent can fix instead of landing in the sales team's list.
"""

import csv
import hashlib
import io
import re
import secrets
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

from . import config, db


class Refused(HTTPException):
    """An action that is not allowed; the message is shown as is."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(status_code=status, detail=message)
        self.message = message


@dataclass
class Actor:
    user_id: str
    name: str
    role: str = ""
    is_agent: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def now() -> int:
    return int(time.time())


def _today() -> date:
    return datetime.fromtimestamp(now(), timezone(timedelta(hours=7))).date()


def new_id() -> str:
    return secrets.token_hex(8)


# ---------------------------------------------------------------- text helpers


def fold(text: str) -> str:
    """Lower case, no Vietnamese marks, single spaces: 'Cà Mau' -> 'ca mau'."""
    text = unicodedata.normalize("NFD", str(text or "")).replace("đ", "d").replace("Đ", "D")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


_PROVINCE_INDEX: list[tuple[str, str, str]] = []  # (folded name, new province, name as written)


def _province_index() -> list[tuple[str, str, str]]:
    if not _PROVINCE_INDEX:
        rows = []
        for table in (config.PROVINCES, config.OTHER_PROVINCES):
            for new, olds in table.items():
                for name in [new, *olds]:
                    rows.append((fold(name.replace("TP. ", "")), new, name))
        for alias, new in config.PROVINCE_ALIASES.items():
            rows.append((fold(alias), new, alias))
        rows.sort(key=lambda r: -len(r[0]))  # longest first: "ba ria vung tau" before "vung tau"
        _PROVINCE_INDEX.extend(rows)
    return _PROVINCE_INDEX


def province_of(text: str) -> tuple[str, str]:
    """(new province, name found) for a place written old or new style; ('', '') when none is named."""
    folded = f" {fold(text)} "
    if not folded.strip():
        return "", ""
    for key, new, written in _province_index():
        if f" {key} " in folded:
            return new, written
    return "", ""


_COMPANY_WORDS = (
    "cong ty co phan", "cong ty tnhh mot thanh vien", "cong ty tnhh mtv", "cong ty tnhh", "cong ty cp", "cong ty",
    "tong cong ty", "tap doan", "ctcp", "tnhh", "mtv", "co phan", "joint stock company", "jsc", "co ltd", "company",
    "limited", "ltd", "corporation", "corp", "group", "viet nam", "vietnam", "chi nhanh", "nha may",
)
_VAGUE_COMPANY = {"", "khong ro", "chua ro", "unknown", "n a", "na", "doanh nghiep", "chu dau tu", "cong ty",
                  "nha dau tu", "mot doanh nghiep", "nha may"}


_VAGUE_PREFIXES = ("chua ro", "khong ro", "chua xac dinh", "khong xac dinh", "chua co ten", "khong co ten",
                   "khong neu", "chua neu", "unknown", "not specified", "n a ", "an danh", "mot cong ty", "mot doanh nghiep",
                   "nha dau tu nuoc ngoai", "doanh nghiep chua", "chu dau tu chua")


_PLACE_PREFIXES = ("chu dau tu", "khu cong nghiep", "kcn ", "cum cong nghiep", "ccn ", "khu kinh te", "tinh ", "thanh pho ",
                   "ubnd", "uy ban nhan dan", "so ", "ban quan ly", "du an ")


_COUNTRIES = ("han quoc", "nhat ban", "trung quoc", "dai loan", "thai lan", "singapore", "malaysia", "indonesia", "an do",
              "hoa ky", "chau au", "nuoc ngoai", "ba lan", "ha lan", "dan mach", "thuy dien", "korea", "japan", "china",
              "taiwan", "fdi")


def _only_descriptors(name: str) -> bool:
    """'Tập đoàn thực phẩm Hàn Quốc', 'Nhà đầu tư Nhật Bản': an industry and a country, no name."""
    key = f" {company_key(name)} "
    found = [c for c in _COUNTRIES if f" {c} " in key]
    if not found:
        return False
    for c in found:
        key = key.replace(f" {c} ", " ")
    rest = key.split()
    return all(w in _GENERIC_WORDS or w in {"nha", "dau", "tu", "doanh", "nghiep", "nhom"} for w in rest)


def vague_company(name: str) -> bool:
    """'Chưa rõ tên doanh nghiệp', 'Chủ đầu tư dự án...', 'Khu công nghiệp Phù Mỹ', 'Cà Mau'... are not a company to call."""
    folded = fold(name)
    padded = f"{folded} "
    return (folded in _VAGUE_COMPANY or len(company_key(name)) < 2 or _only_descriptors(name)
            or any(padded.startswith(p) for p in _VAGUE_PREFIXES + _PLACE_PREFIXES) or " chua ro" in f" {folded}"
            or province_of(name)[1] and fold(province_of(name)[1].replace("TP. ", "")) == folded.removeprefix("tp "))


def company_key(name: str) -> str:
    key = f" {fold(name)} "
    for word in _COMPANY_WORDS:
        key = key.replace(f" {word} ", " ")
    return re.sub(r"\s+", " ", key).strip()


def url_key(url: str) -> str:
    """Same page, different tracking: one key. https/www/trailing slash/utm_ and fragment are ignored."""
    parts = urllib.parse.urlsplit(str(url or "").strip())
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    path = parts.path.rstrip("/") or "/"
    raw = f"{host}{path}?{urllib.parse.urlencode(sorted(query))}" if query else f"{host}{path}"
    return hashlib.sha1(raw.encode()).hexdigest()


def _clean(value, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _parse_day(value) -> date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _epoch(day: date | None) -> int | None:
    if day is None:
        return None
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone(timedelta(hours=7))).timestamp())


# ---------------------------------------------------------------- secrets (Apify key)


def _box():
    from cryptography.fernet import Fernet

    return Fernet(config.SECRET_KEY.encode())


def seal(value: str) -> str:
    return _box().encrypt(value.encode()).decode()


def unseal(value: str) -> str:
    from cryptography.fernet import InvalidToken

    try:
        return _box().decrypt(value.encode()).decode()
    except InvalidToken as error:
        raise Refused("Không giải mã được key Apify đã lưu; nhập lại trong Cài đặt.", 500) from error


def apify_key() -> str:
    sealed = db.get_kv("apify_key")
    return unseal(sealed) if sealed else ""


def key_status() -> dict:
    key = apify_key()
    status = db.get_kv("apify_status", {}) or {}
    return {"set": bool(key), "last4": key[-4:] if key else "", **{k: status.get(k) for k in
            ("ok", "username", "plan", "used_usd", "limit_usd", "cycle_end", "checked_at", "error")}}


def _apify_get(key: str, path: str) -> dict:
    req = urllib.request.Request(f"{config.APIFY_API}{path}", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT_SECONDS) as res:
        import json

        return json.load(res).get("data") or {}


def check_key(key: str | None = None) -> dict:
    """Ask Apify who the key belongs to and how much of the month is used. Saves the result for the page."""
    key = key or apify_key()
    if not key:
        raise Refused("Chưa có key Apify. Nhập key trong Cài đặt.")
    try:
        me = _apify_get(key, "/users/me")
        limits = _apify_get(key, "/users/me/limits")
        plan = me.get("plan") or {}
        status = {
            "ok": True,
            "username": me.get("username") or "",
            "plan": plan.get("id") or "",
            "used_usd": round(float((limits.get("current") or {}).get("monthlyUsageUsd") or 0), 3),
            "limit_usd": float((limits.get("limits") or {}).get("maxMonthlyUsageUsd") or 0),
            "cycle_end": ((limits.get("monthlyUsageCycle") or {}).get("endAt") or "")[:10],
            "checked_at": now(),
            "error": "",
        }
    except urllib.error.HTTPError as error:
        message = "Key Apify không đúng hoặc đã bị thu hồi." if error.code in (401, 403) else f"Apify trả lỗi {error.code}."
        status = {"ok": False, "checked_at": now(), "error": message}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        status = {"ok": False, "checked_at": now(), "error": f"Không gọi được Apify: {error}"}
    with db.tx() as conn:
        db.set_kv(conn, "apify_status", status)
    return status


def save_key(actor: Actor, key: str) -> dict:
    if not actor.is_admin:
        raise Refused("Chỉ quản trị viên mới nhập hoặc đổi key Apify.", 403)
    key = (key or "").strip()
    if not re.fullmatch(r"apify_api_[A-Za-z0-9]{20,}", key):
        raise Refused("Key Apify có dạng apify_api_… (Apify Console → Settings → API & Integrations).")
    status = check_key(key)
    if not status.get("ok"):
        raise Refused(status.get("error") or "Apify không nhận key này.")
    with db.tx() as conn:
        db.set_kv(conn, "apify_key", seal(key))
    return key_status()


def delete_key(actor: Actor) -> dict:
    if not actor.is_admin:
        raise Refused("Chỉ quản trị viên mới xoá được key Apify.", 403)
    with db.tx() as conn:
        conn.execute("DELETE FROM kv WHERE key IN ('apify_key', 'apify_status')")
    return key_status()


# ---------------------------------------------------------------- settings


def get_settings() -> dict:
    saved = db.get_kv("settings", {}) or {}
    out = {}
    for key, default in config.DEFAULT_SETTINGS.items():
        value = saved.get(key, default)
        if isinstance(default, dict):
            value = {**default, **(value if isinstance(value, dict) else {})}
        out[key] = value
    return out


def _num(value, low, high, name):
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise Refused(f"{name}: cần một con số.") from error
    if not low <= number <= high:
        raise Refused(f"{name}: trong khoảng {low} – {high}.")
    return number


def save_settings(actor: Actor, patch: dict) -> dict:
    if not actor.is_admin:
        raise Refused("Chỉ quản trị viên mới đổi được cài đặt Săn lead.", 403)
    current = get_settings()
    if "seller" in patch:
        seller = patch["seller"] or {}
        current["seller"] = {k: _clean(seller.get(k, current["seller"].get(k, "")), 2000) for k in ("company", "products", "avoid")}
    for key, allowed in (("industries", config.INDUSTRIES), ("priority_industries", config.INDUSTRIES),
                         ("kinds", config.KINDS)):
        if key in patch:
            values = [v for v in (patch[key] or []) if v in allowed]
            current[key] = list(dict.fromkeys(values))
    if "industries" in patch and not current["industries"]:
        raise Refused("Chọn ít nhất một ngành.")
    if "kinds" in patch and not current["kinds"]:
        raise Refused("Chọn ít nhất một loại cơ hội.")
    if "provinces" in patch:
        known = {**config.PROVINCES, **config.OTHER_PROVINCES}
        current["provinces"] = [p for p in dict.fromkeys(patch["provinces"] or []) if p in known]
        if not current["provinces"]:
            raise Refused("Chọn ít nhất một tỉnh.")
    if "sources" in patch:
        current["sources"] = {k: bool((patch["sources"] or {}).get(k, current["sources"].get(k)))
                              for k in config.DEFAULT_SETTINGS["sources"]}
    if "watch_pages" in patch:
        pages = []
        for page in (patch["watch_pages"] or [])[:80]:
            url = _clean((page or {}).get("url"), 500)
            if not url:
                continue
            if not re.match(r"https?://", url):
                raise Refused(f"Trang theo dõi phải bắt đầu bằng http:// hoặc https:// ({url}).")
            pages.append({"url": url, "label": _clean(page.get("label"), 120)})
        current["watch_pages"] = pages
    if "extra_keywords" in patch:
        current["extra_keywords"] = [w for w in (_clean(x, 80) for x in (patch["extra_keywords"] or [])[:40]) if w]
    for key, low, high, name in (("google_queries_per_run", 0, 80, "Số truy vấn Google mỗi lần"),
                                 ("people_per_opportunity", 0, 10, "Số người mỗi cơ hội"),
                                 ("linkedin_sweep_per_run", 0, 200, "Số hồ sơ tìm theo chức danh"),
                                 ("min_score_for_people", 0, 100, "Điểm tối thiểu để tìm người"),
                                 ("lookback_days", 7, 365, "Số ngày nhìn lại")):
        if key in patch:
            current[key] = int(_num(patch[key], low, high, name))
    for key, low, high, name in (("max_usd_per_run", 0, 20, "Trần mỗi lần quét (USD)"),
                                 ("max_usd_per_month", 0, 500, "Trần mỗi tháng (USD)")):
        if key in patch:
            current[key] = round(_num(patch[key], low, high, name), 2)
    if "llm_model" in patch:
        current["llm_model"] = _clean(patch["llm_model"], 120)
    with db.tx() as conn:
        db.set_kv(conn, "settings", current)
    return current


# ---------------------------------------------------------------- scoring


def _equipment_matches(equipment: list[str], products: str) -> bool:
    words = {w for w in fold(products).split() if len(w) >= 4}
    if not words:
        return False
    stop = {"thiet", "may", "he", "thong", "cho", "nha", "phong", "cong", "nghiep", "san", "xuat"}
    words -= stop
    for item in equipment:
        if words & ({w for w in fold(item).split() if len(w) >= 4} - stop):
            return True
    return False


def score(opp: dict, settings: dict, people_count: int = 0) -> tuple[int, list[str]]:
    points, reasons = 0, []
    kind = opp["kind"]
    deadline = _parse_day(opp.get("deadline"))
    if kind == "moi_thau":
        if deadline and deadline >= _today():
            points += 35
            reasons.append(f"+35 mời thầu còn hạn ({deadline.strftime('%d/%m/%Y')})")
        else:
            points += 26
            reasons.append("+26 mời thầu / chào giá")
    else:
        bonus = {"du_an_moi": 30, "mo_rong": 25, "tin_hieu": 15}[kind]
        points += bonus
        reasons.append(f"+{bonus} {config.KINDS[kind].lower()}")
    if opp["industry"] in settings.get("priority_industries", []):
        points += 15
        reasons.append(f"+15 ngành ưu tiên ({config.INDUSTRY_SHORT[opp['industry']]})")
    else:
        points += 8
        reasons.append(f"+8 ngành theo dõi ({config.INDUSTRY_SHORT[opp['industry']]})")
    if opp.get("province") and opp["province"] in settings.get("provinces", []):
        points += 10
        reasons.append(f"+10 trong vùng ({opp['province']})")
    published = opp.get("published_at")
    if published:
        age = (now() - published) / 86400
        if age <= 14:
            points += 15
            reasons.append("+15 tin trong 2 tuần")
        elif age <= 45:
            points += 8
            reasons.append("+8 tin trong 45 ngày")
    else:
        points += 4
        reasons.append("+4 chưa rõ ngày tin")
    equipment = opp.get("equipment") or []
    products = (settings.get("seller") or {}).get("products", "")
    if equipment and _equipment_matches(equipment, products):
        bonus = 8 if opp.get("equipment_inferred") else 15
        points += bonus
        reasons.append(f"+{bonus} thiết bị khớp hàng đang bán" + (" (gợi ý)" if bonus == 8 else ""))
    elif equipment and not products.strip():
        points += 5
        reasons.append("+5 có hạng mục thiết bị (chưa nhập hàng đang bán để so)")
    contact = opp.get("contact") or {}
    if people_count or any(contact.get(k) for k in ("name", "phone", "email")):
        points += 10
        reasons.append("+10 có người / đầu mối liên hệ")
    return min(points, 100), reasons


# ---------------------------------------------------------------- opportunities


def _bucket(kind: str) -> str:
    return "tender" if kind == "moi_thau" else "project"


def _dedupe_key(company: str, kind: str, province: str, title: str) -> str:
    base = f"{company_key(company)}|{fold(province)}|{_bucket(kind)}"
    if kind == "moi_thau":
        base += "|" + fold(title)[:80]
    return base


# Words too common to name a company on their own ("Thủy sản" + "Hậu Giang" are not one company with "Dược Hậu Giang").
_GENERIC_WORDS = set("""thuy san hai duoc pham thuc an uong sua viet nam phat minh hoang long thanh phu quoc te sai gon
mekong tan hung cuu dong bac trung tay nong nghiep che bien xuat nhap khau dau tu thuong mai dich vu thiet bi y khoa hoc
ky thuat cong nghe moi truong sinh hoc thu chan nuoi hoa chat my nha may mien sao vang kim ngoc bao an binh thinh loc
phuc dai vinh hau giang ca mau can tho bach hop tac xa cp tm dv sx xnk""".split())


def _same_company(a: str, b: str) -> bool:
    """'minh phu' and 'thuy san minh phu' are one company; 'duoc hau giang' and 'thuy san hau giang' are not;
    'baf' (one distinctive word) and 'che bien thuc pham baf binh dinh' are one."""
    if a == b:
        return True
    small, big = sorted((set(a.split()), set(b.split())), key=len)
    if not small or not small <= big:
        return False
    if len(small) >= 2:
        return True
    word = next(iter(small))
    return len(word) >= 3 and word not in _GENERIC_WORDS


def _core(key: str) -> set:
    """The words that name the company: no legal form, no common words, no province names ('baf binh dinh' -> {'baf'})."""
    words = f" {key} "
    for _, _, written in _province_index():
        words = words.replace(f" {fold(written)} ", " ")
    return {w for w in words.split() if len(w) >= 3 and w not in _GENERIC_WORDS}


def _same_company_loose(a: str, b: str) -> bool:
    """'BAF Bình Định' and 'Nông nghiệp BAF Việt Nam': the same name once common words and places are dropped."""
    if _same_company(a, b):
        return True
    ca, cb = _core(a), _core(b)
    return bool(ca) and bool(cb) and (ca <= cb or cb <= ca)


def _similar(conn, key: str):
    """An opportunity filed under a slightly different company name: same province (or none), same bucket, and for
    tenders the same package name."""
    company, province, bucket, *rest = key.split("|")
    rows = conn.execute("SELECT * FROM opportunities WHERE dedupe_key LIKE ?", (f"%|{bucket}%",)).fetchall()
    for row in rows:
        other, other_province, _, *other_rest = row["dedupe_key"].split("|")
        if rest != other_rest:
            continue
        if province and other_province and province != other_province:
            continue
        if _same_company_loose(company, other):
            return row
    return None


_KIND_RANK = {"du_an_moi": 3, "mo_rong": 2, "tin_hieu": 1, "moi_thau": 0}


def _sources(raw) -> list[dict]:
    out, keys = [], set()
    for item in raw or []:
        if isinstance(item, str):
            item = {"url": item}
        url = _clean((item or {}).get("url"), 1000)
        if not re.match(r"https?://", url):
            continue
        key = url_key(url)
        if key in keys:
            continue
        keys.add(key)
        day = _parse_day(item.get("published"))
        out.append({"url": url, "title": _clean(item.get("title"), 300), "site": urllib.parse.urlsplit(url).netloc,
                    "published": day.isoformat() if day else ""})
    out.sort(key=lambda s: s["site"] == "news.google.com")  # the article itself first, Google News redirects last
    return out


def validate_opportunity(item: dict, settings: dict) -> dict:
    """The cleaned opportunity, or Refused with the reason (shown to the agent)."""
    if not isinstance(item, dict):
        raise Refused("không phải object")
    company = _clean(item.get("company"), 200)
    if vague_company(company):
        raise Refused("thiếu tên doanh nghiệp / chủ đầu tư cụ thể")
    industry = item.get("industry")
    if industry not in config.INDUSTRIES:
        raise Refused(f"ngành '{industry}' không thuộc 7 ngành ({', '.join(config.INDUSTRIES)})")
    if industry not in settings["industries"]:
        raise Refused(f"ngành {config.INDUSTRY_SHORT[industry]} đang tắt trong Cài đặt")
    kind = item.get("kind")
    if kind not in config.KINDS:
        raise Refused(f"loại '{kind}' không hợp lệ ({', '.join(config.KINDS)})")
    if kind not in settings["kinds"]:
        raise Refused(f"loại {config.KINDS[kind]} đang tắt trong Cài đặt")
    sources = _sources(item.get("sources") or ([item["url"]] if item.get("url") else []))
    if not sources:
        raise Refused("thiếu link nguồn (sources[].url)")
    written = _clean(item.get("province"), 80)
    location = _clean(item.get("location"), 200)
    province, found = province_of(written) if written else ("", "")
    if not province and location:
        province, found = province_of(location)
    if written and not province:
        raise Refused(f"không nhận ra tỉnh '{written}'")
    if province and province not in settings["provinces"]:
        raise Refused(f"ngoài vùng theo dõi ({province})")
    title = _clean(item.get("title"), 300)
    if kind == "moi_thau" and not title:
        raise Refused("mời thầu cần tên gói (title)")
    deadline = _parse_day(item.get("deadline"))
    if item.get("deadline") and deadline is None:
        raise Refused(f"hạn chót '{item.get('deadline')}' không đọc được (dùng YYYY-MM-DD)")
    if kind == "moi_thau" and deadline and deadline < _today():
        raise Refused(f"gói đã hết hạn ({deadline.isoformat()})")
    published = _parse_day(item.get("published")) or next(
        (_parse_day(s["published"]) for s in sources if s["published"]), None)
    if published and published > _today() + timedelta(days=1):
        published = None  # a date in the future is a misread, not a fact
    if published and (_today() - published).days > settings["lookback_days"] and not (deadline and deadline >= _today()):
        raise Refused(f"tin cũ ({published.isoformat()}, quá {settings['lookback_days']} ngày)")
    if kind == "tin_hieu" and not published:
        raise Refused("tín hiệu không rõ ngày (không biết còn mới không)")
    raw_equipment = item.get("equipment") or []
    if isinstance(raw_equipment, str):  # "máy A, máy B" from a sloppy extraction
        raw_equipment = re.split(r"[;,\n]+", raw_equipment)
    equipment = [e for e in (_clean(x, 120) for x in list(raw_equipment)[:15]) if len(e) >= 3]
    contact = item.get("contact") or {}
    contact = {k: _clean(contact.get(k), 160) for k in ("name", "phone", "email")} if isinstance(contact, dict) else {}
    plant_status = item.get("plant_status") if item.get("plant_status") in config.PLANT_STATUS else (
        "du_an_moi" if kind == "du_an_moi" else "dang_chay" if kind == "mo_rong" else "chua_ro")
    found_old = found if found and fold(found) != fold(province.replace("TP. ", "")) else ""
    return {
        "company": company,
        "industry": industry,
        "kind": kind,
        "plant_status": plant_status,
        "title": title,
        "summary": _clean(item.get("summary"), 700),
        "province": province,
        "province_old": found_old,
        "location": location,
        "equipment": equipment,
        "equipment_inferred": bool(item.get("equipment_inferred")),
        "deadline": deadline.isoformat() if deadline else None,
        "progress": _clean(item.get("progress"), 300),
        "value_text": _clean(item.get("value"), 120),
        "contact": contact,
        "sales_note": _clean(item.get("sales_note"), 900),
        "sources": sources,
        "published_at": _epoch(published),
    }


def _row_opp(row) -> dict:
    out = dict(row)
    for key, fallback in (("equipment", []), ("contact", {}), ("sources", []), ("score_reasons", [])):
        out[key] = db.loads(out[key], fallback)
    out["equipment_inferred"] = bool(out["equipment_inferred"])
    out["industry_label"] = config.INDUSTRY_SHORT.get(out["industry"], out["industry"])
    out["kind_label"] = config.KINDS.get(out["kind"], out["kind"])
    out["state_label"] = config.STATES.get(out["state"], out["state"])
    out.pop("dedupe_key", None)
    return out


def upsert_opportunities(items: list, run_id: str | None = None) -> dict:
    if not isinstance(items, list):
        raise Refused("items phải là danh sách")
    if len(items) > config.MAX_BATCH:
        raise Refused(f"Tối đa {config.MAX_BATCH} cơ hội mỗi lần gửi.")
    settings = get_settings()
    created, merged, rejected = [], [], []
    stamp = now()
    for index, raw in enumerate(items):
        try:
            opp = validate_opportunity(raw, settings)
        except Refused as error:
            rejected.append({"index": index, "company": _clean((raw or {}).get("company"), 80) if isinstance(raw, dict) else "",
                             "reason": error.message})
            continue
        key = _dedupe_key(opp["company"], opp["kind"], opp["province"], opp["title"])
        with db.tx() as conn:
            row = conn.execute("SELECT * FROM opportunities WHERE dedupe_key=?", (key,)).fetchone() or _similar(conn, key)
            if row is None:
                opp_id = new_id()
                people = 0
                points, reasons = score({**opp}, settings, people)
                conn.execute(
                    "INSERT INTO opportunities (id, dedupe_key, company, industry, kind, plant_status, title, summary, "
                    "province, province_old, location, equipment, equipment_inferred, deadline, progress, value_text, "
                    "contact, sales_note, sources, published_at, score, score_reasons, run_id, first_seen, last_seen, "
                    "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (opp_id, key, opp["company"], opp["industry"], opp["kind"], opp["plant_status"], opp["title"],
                     opp["summary"], opp["province"], opp["province_old"], opp["location"], db.dumps(opp["equipment"]),
                     int(opp["equipment_inferred"]), opp["deadline"], opp["progress"], opp["value_text"],
                     db.dumps(opp["contact"]), opp["sales_note"], db.dumps(opp["sources"]), opp["published_at"], points,
                     db.dumps(reasons), run_id, stamp, stamp, stamp))
                created.append({"index": index, "id": opp_id, "company": opp["company"], "score": points})
                continue
            old = _row_opp(row)
            sources = _sources(old["sources"] + opp["sources"])
            equipment = list(dict.fromkeys(old["equipment"] + opp["equipment"]))[:15]
            kind = old["kind"] if _KIND_RANK[old["kind"]] >= _KIND_RANK[opp["kind"]] else opp["kind"]
            contact = {k: old["contact"].get(k) or opp["contact"].get(k, "") for k in ("name", "phone", "email")}
            mixed = {
                **old,
                "kind": kind,
                "plant_status": opp["plant_status"] if old["plant_status"] == "chua_ro" else old["plant_status"],
                "title": old["title"] or opp["title"],
                "summary": old["summary"] if len(old["summary"]) >= len(opp["summary"]) else opp["summary"],
                "province": old["province"] or opp["province"],
                "province_old": old["province_old"] or opp["province_old"],
                "location": old["location"] if len(old["location"]) >= len(opp["location"]) else opp["location"],
                "equipment": equipment,
                "equipment_inferred": old["equipment_inferred"] and opp["equipment_inferred"],
                "deadline": opp["deadline"] or old["deadline"],
                "progress": opp["progress"] or old["progress"],
                "value_text": old["value_text"] or opp["value_text"],
                "contact": contact,
                "sales_note": old["sales_note"] or opp["sales_note"],
                "sources": sources,
                "published_at": max(filter(None, [old["published_at"], opp["published_at"]]), default=None),
            }
            people = conn.execute("SELECT COUNT(*) FROM people WHERE opportunity_id=?", (old["id"],)).fetchone()[0]
            points, reasons = score(mixed, settings, people)
            conn.execute(
                "UPDATE opportunities SET kind=?, plant_status=?, title=?, summary=?, province=?, province_old=?, "
                "location=?, equipment=?, equipment_inferred=?, deadline=?, progress=?, value_text=?, contact=?, "
                "sales_note=?, sources=?, published_at=?, score=?, score_reasons=?, last_seen=?, updated_at=? WHERE id=?",
                (mixed["kind"], mixed["plant_status"], mixed["title"], mixed["summary"], mixed["province"],
                 mixed["province_old"], mixed["location"], db.dumps(equipment), int(mixed["equipment_inferred"]),
                 mixed["deadline"], mixed["progress"], mixed["value_text"], db.dumps(contact), mixed["sales_note"],
                 db.dumps(sources), mixed["published_at"], points, db.dumps(reasons), stamp, stamp, old["id"]))
            merged.append({"index": index, "id": old["id"], "company": old["company"], "score": points,
                           "new_sources": len(sources) - len(old["sources"])})
    return {"created": created, "merged": merged, "rejected": rejected}


def _rescore(conn, opp_id: str) -> None:
    row = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
    if row is None:
        return
    people = conn.execute("SELECT COUNT(*) FROM people WHERE opportunity_id=?", (opp_id,)).fetchone()[0]
    points, reasons = score(_row_opp(row), get_settings(), people)
    conn.execute("UPDATE opportunities SET score=?, score_reasons=? WHERE id=?", (points, db.dumps(reasons), opp_id))


def _where(filters: dict, table: str) -> tuple[str, list]:
    clauses, params = [], []
    for key in ("state", "industry", "kind", "province", "role_group"):
        value = filters.get(key)
        if value:
            clauses.append(f"{key}=?")
            params.append(value)
    if table == "opportunities" and filters.get("min_score"):
        clauses.append("score>=?")
        params.append(int(filters["min_score"]))
    if filters.get("opportunity_id"):
        clauses.append("opportunity_id=?")
        params.append(filters["opportunity_id"])
    if filters.get("since"):
        clauses.append("first_seen>=?")
        params.append(int(filters["since"]))
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _matches(row: dict, q: str, fields: tuple) -> bool:
    words = fold(q).split()
    hay = fold(" ".join(str(row.get(f) or "") for f in fields))
    return all(w in hay for w in words)


def list_opportunities(filters: dict) -> dict:
    where, params = _where(filters, "opportunities")
    order = {"new": "first_seen DESC", "deadline": "deadline IS NULL, deadline ASC", "score": "score DESC, first_seen DESC"}.get(
        filters.get("sort") or "score", "score DESC, first_seen DESC")
    rows = [_row_opp(r) for r in db.query(f"SELECT * FROM opportunities{where} ORDER BY {order}", tuple(params))]
    if filters.get("q"):
        rows = [r for r in rows if _matches(r, filters["q"], ("company", "title", "summary", "province", "province_old",
                                                              "location", "equipment", "sales_note"))]
    counts = {k: 0 for k in config.STATES}
    for row in db.query("SELECT state, COUNT(*) AS n FROM opportunities GROUP BY state"):
        counts[row["state"]] = row["n"]
    people = {r["opportunity_id"]: r["n"] for r in
              db.query("SELECT opportunity_id, COUNT(*) AS n FROM people WHERE opportunity_id IS NOT NULL GROUP BY opportunity_id")}
    total = len(rows)
    offset = max(0, int(filters.get("offset") or 0))
    limit = max(1, min(int(filters.get("limit") or 100), config.MAX_LIST))
    page = rows[offset:offset + limit]
    for row in page:
        row["people_count"] = people.get(row["id"], 0)
    return {"items": page, "total": total, "counts": counts}


def get_opportunity(opp_id: str) -> dict:
    row = db.one("SELECT * FROM opportunities WHERE id=?", (opp_id,))
    if row is None:
        raise Refused("Không thấy cơ hội này.", 404)
    out = _row_opp(row)
    out["people"] = [_row_person(r) for r in db.query("SELECT * FROM people WHERE opportunity_id=? ORDER BY first_seen", (opp_id,))]
    out["people_count"] = len(out["people"])
    return out


def _set_state(table: str, actor: Actor, item_id: str, patch: dict) -> None:
    fields, params = [], []
    if "state" in patch and patch["state"] is not None:
        if patch["state"] not in config.STATES:
            raise Refused("Trạng thái không hợp lệ.")
        fields += ["state=?", "state_by=?", "state_at=?"]
        params += [patch["state"], actor.name, now()]
    if "note" in patch and patch["note"] is not None:
        fields.append("note=?")
        params.append(_clean(patch["note"], 2000))
    if not fields:
        return
    with db.tx() as conn:
        done = conn.execute(f"UPDATE {table} SET {', '.join(fields)}, updated_at=? WHERE id=?", (*params, now(), item_id))
        if done.rowcount == 0:
            raise Refused("Không thấy mục này.", 404)


def patch_opportunity(actor: Actor, opp_id: str, patch: dict) -> dict:
    if actor.is_agent:
        raise Refused("Agent không đổi trạng thái hay ghi chú của sale.", 403)
    _set_state("opportunities", actor, opp_id, patch)
    return get_opportunity(opp_id)


def delete_item(actor: Actor, table: str, item_id: str) -> None:
    if not actor.is_admin:
        raise Refused("Chỉ quản trị viên mới xoá được.", 403)
    with db.tx() as conn:
        if table == "opportunities":
            conn.execute("UPDATE people SET opportunity_id=NULL WHERE opportunity_id=?", (item_id,))
        opp = conn.execute("SELECT opportunity_id FROM people WHERE id=?", (item_id,)).fetchone() if table == "people" else None
        if conn.execute(f"DELETE FROM {table} WHERE id=?", (item_id,)).rowcount == 0:
            raise Refused("Không thấy mục này.", 404)
        if opp and opp["opportunity_id"]:
            _rescore(conn, opp["opportunity_id"])


# ---------------------------------------------------------------- people

_LINKEDIN_PROFILE = re.compile(r"https?://([a-z]{2,3}\.)?(www\.)?linkedin\.com/in/[^/?#\s]+", re.I)
_ROLE_WORDS = {
    "mua_sam": ("procurement", "purchasing", "purchase", "sourcing", "supply chain", "buyer", "mua hang", "mua sam",
                "general manager", "general director", "tong giam doc", "pho tong giam doc", "ceo", "chairman", "owner"),
    "san_xuat_qa": ("production", "operations", "operation", "qa", "qc", "quality", "r d", "r&d", "san xuat",
                    "chat luong", "lab"),
    "ky_thuat": ("project", "plant", "factory", "technical", "engineering", "maintenance", "chief engineer",
                 "ky thuat", "du an", "co dien", "nha may", "giam doc nha may"),
}


def role_of(title: str) -> str:
    folded = f" {fold(title)} "
    for group, words in _ROLE_WORDS.items():
        if any(f" {fold(w)} " in folded for w in words):
            return group
    return "khac"


def linkedin_url(value: str) -> str:
    match = _LINKEDIN_PROFILE.search(str(value or ""))
    if not match:
        return ""
    url = match.group(0)
    return re.sub(r"https?://([a-z]{2,3}\.)?(www\.)?linkedin\.com", "https://www.linkedin.com", url, flags=re.I).rstrip("/")


def validate_person(item: dict, settings: dict) -> dict:
    if not isinstance(item, dict):
        raise Refused("không phải object")
    name = _clean(item.get("name"), 120)
    if len(fold(name)) < 2 or fold(name) in {"linkedin member", "thanh vien linkedin", "unknown"}:
        raise Refused("thiếu tên người")
    company = _clean(item.get("company"), 200)
    if vague_company(company):
        raise Refused("thiếu công ty")
    url = linkedin_url(item.get("linkedin_url"))
    if item.get("linkedin_url") and not url:
        raise Refused("link LinkedIn không phải link hồ sơ (linkedin.com/in/...)")
    title = _clean(item.get("title"), 200)
    if not title:
        raise Refused("thiếu chức danh")
    role = item.get("role_group") if item.get("role_group") in config.ROLE_GROUPS else "khac"
    if role == "khac":
        role = role_of(title)
    industry = item.get("industry") if item.get("industry") in config.INDUSTRIES else ""
    location = _clean(item.get("location") or item.get("province"), 200)
    province = province_of(location)[0] if location else ""
    email = _clean(item.get("email"), 160)
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email, re.I):
        email = ""
    opp_id = item.get("opportunity_id") or None
    if opp_id and db.one("SELECT 1 FROM opportunities WHERE id=?", (opp_id,)) is None:
        raise Refused(f"không thấy cơ hội {opp_id}")
    plant_status = item.get("plant_status") if item.get("plant_status") in config.PLANT_STATUS else "chua_ro"
    return {"name": name, "title": title, "company": company, "industry": industry, "plant_status": plant_status,
            "role_group": role, "province": province, "location": location, "linkedin_url": url, "email": email,
            "phone": _clean(item.get("phone"), 40), "sales_note": _clean(item.get("sales_note"), 900),
            "source": _clean(item.get("source"), 60), "opportunity_id": opp_id}


def _row_person(row) -> dict:
    out = dict(row)
    out["role_label"] = config.ROLE_GROUPS.get(out["role_group"], out["role_group"])
    out["industry_label"] = config.INDUSTRY_SHORT.get(out["industry"], "")
    out["state_label"] = config.STATES.get(out["state"], out["state"])
    out.pop("dedupe_key", None)
    return out


def upsert_people(items: list, run_id: str | None = None) -> dict:
    if not isinstance(items, list):
        raise Refused("items phải là danh sách")
    if len(items) > config.MAX_BATCH:
        raise Refused(f"Tối đa {config.MAX_BATCH} người mỗi lần gửi.")
    settings = get_settings()
    created, merged, rejected = [], [], []
    stamp = now()
    for index, raw in enumerate(items):
        try:
            person = validate_person(raw, settings)
        except Refused as error:
            rejected.append({"index": index, "name": _clean((raw or {}).get("name"), 80) if isinstance(raw, dict) else "",
                             "reason": error.message})
            continue
        key = person["linkedin_url"].lower() or f"{fold(person['name'])}|{company_key(person['company'])}"
        with db.tx() as conn:
            row = conn.execute("SELECT * FROM people WHERE dedupe_key=?", (key,)).fetchone()
            if row is None:
                person_id = new_id()
                conn.execute(
                    "INSERT INTO people (id, dedupe_key, name, title, company, industry, plant_status, role_group, "
                    "province, location, linkedin_url, email, phone, sales_note, source, opportunity_id, run_id, "
                    "first_seen, last_seen, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (person_id, key, person["name"], person["title"], person["company"], person["industry"],
                     person["plant_status"], person["role_group"], person["province"], person["location"],
                     person["linkedin_url"], person["email"], person["phone"], person["sales_note"], person["source"],
                     person["opportunity_id"], run_id, stamp, stamp, stamp))
                created.append({"index": index, "id": person_id, "name": person["name"]})
            else:
                old = dict(row)
                person_id = old["id"]
                conn.execute(
                    "UPDATE people SET title=?, company=?, industry=?, plant_status=?, role_group=?, province=?, "
                    "location=?, email=?, phone=?, sales_note=?, opportunity_id=?, last_seen=?, updated_at=? WHERE id=?",
                    (person["title"] or old["title"], person["company"] or old["company"],
                     person["industry"] or old["industry"],
                     person["plant_status"] if person["plant_status"] != "chua_ro" else old["plant_status"],
                     person["role_group"] if person["role_group"] != "khac" else old["role_group"],
                     person["province"] or old["province"], person["location"] or old["location"],
                     person["email"] or old["email"], person["phone"] or old["phone"],
                     person["sales_note"] or old["sales_note"], person["opportunity_id"] or old["opportunity_id"],
                     stamp, stamp, person_id))
                merged.append({"index": index, "id": person_id, "name": person["name"]})
            for opp_id in {person["opportunity_id"], row["opportunity_id"] if row else None} - {None}:
                _rescore(conn, opp_id)
    return {"created": created, "merged": merged, "rejected": rejected}


def list_people(filters: dict) -> dict:
    where, params = _where(filters, "people")
    rows = [_row_person(r) for r in db.query(f"SELECT * FROM people{where} ORDER BY first_seen DESC", tuple(params))]
    if filters.get("q"):
        rows = [r for r in rows if _matches(r, filters["q"], ("name", "title", "company", "province", "location", "sales_note"))]
    companies = {r["id"]: r["company"] for r in db.query("SELECT id, company FROM opportunities")}
    total = len(rows)
    offset = max(0, int(filters.get("offset") or 0))
    limit = max(1, min(int(filters.get("limit") or 100), config.MAX_LIST))
    page = rows[offset:offset + limit]
    for row in page:
        row["opportunity_company"] = companies.get(row["opportunity_id"] or "", "")
    return {"items": page, "total": total}


def patch_person(actor: Actor, person_id: str, patch: dict) -> dict:
    if actor.is_agent:
        raise Refused("Agent không đổi trạng thái hay ghi chú của sale.", 403)
    _set_state("people", actor, person_id, patch)
    row = db.one("SELECT * FROM people WHERE id=?", (person_id,))
    return _row_person(row)


# ---------------------------------------------------------------- seen links and runs


def unseen(urls: list) -> list[str]:
    urls = [str(u) for u in (urls or [])][:3000]
    keys: dict[str, str] = {}
    for url in urls:
        keys.setdefault(url_key(url), url)
    if not keys:
        return []
    known = set()
    items = list(keys)
    for start in range(0, len(items), 500):
        chunk = items[start:start + 500]
        rows = db.query(f"SELECT url_key FROM seen WHERE url_key IN ({','.join('?' * len(chunk))})", tuple(chunk))
        known |= {r["url_key"] for r in rows}
    return [keys[k] for k in items if k not in known]


def mark_seen(items: list) -> int:
    stamp = now()
    count = 0
    with db.tx() as conn:
        for item in (items or [])[:3000]:
            if isinstance(item, str):
                item = {"url": item}
            url = _clean((item or {}).get("url"), 1000)
            if not url:
                continue
            conn.execute("INSERT INTO seen (url_key, url, verdict, at) VALUES (?,?,?,?) ON CONFLICT(url_key) DO UPDATE "
                         "SET verdict=excluded.verdict, at=excluded.at", (url_key(url), url, _clean(item.get("verdict"), 200), stamp))
            count += 1
    return count


def start_run(trigger: str) -> dict:
    run_id = new_id()
    with db.tx() as conn:
        conn.execute("INSERT INTO runs (id, started_at, trigger) VALUES (?,?,?)", (run_id, now(), _clean(trigger, 60)))
    return {"id": run_id}


def finish_run(run_id: str, patch: dict) -> dict:
    status = patch.get("status") if patch.get("status") in ("ok", "error", "partial", "running") else "ok"
    with db.tx() as conn:
        done = conn.execute(
            "UPDATE runs SET finished_at=?, status=?, stats=?, cost_usd=?, message=? WHERE id=?",
            (None if status == "running" else now(), status, db.dumps(patch.get("stats") or {}),
             round(float(patch.get("cost_usd") or 0), 4), _clean(patch.get("message"), 2000), run_id))
        if done.rowcount == 0:
            raise Refused("Không thấy lần quét này.", 404)
    return list_runs(1)[0]


def list_runs(limit: int = 30) -> list[dict]:
    rows = db.query("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (max(1, min(limit, 200)),))
    out = []
    for row in rows:
        item = dict(row)
        item["stats"] = db.loads(item["stats"], {})
        out.append(item)
    return out


def month_cost() -> float:
    start = datetime.fromtimestamp(now(), timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    row = db.one("SELECT COALESCE(SUM(cost_usd), 0) AS c FROM runs WHERE started_at>=?", (int(start.timestamp()),))
    return round(float(row["c"]), 4)


# ---------------------------------------------------------------- export


def export_csv(table: str) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    if table == "opportunities":
        writer.writerow(["Tên doanh nghiệp / Chủ đầu tư", "Ngành", "Loại", "Trạng thái nhà máy", "Tên gói / dự án",
                         "Tỉnh (mới)", "Tỉnh trong nguồn", "Địa điểm (KCN/CCN)", "Hạng mục thiết bị", "Thiết bị là gợi ý",
                         "Hạn chót", "Tiến độ", "Giá trị", "Đầu mối", "SĐT", "Email", "Tóm tắt", "Gợi ý tiếp cận",
                         "Điểm", "Trạng thái", "Ghi chú", "Nguồn", "Ngày tin", "Agent tìm thấy"])
        for row in list_opportunities({"limit": config.MAX_LIST, "sort": "score"})["items"]:
            contact = row["contact"]
            writer.writerow([row["company"], row["industry_label"], row["kind_label"],
                             config.PLANT_STATUS.get(row["plant_status"], ""), row["title"], row["province"],
                             row["province_old"], row["location"], "; ".join(row["equipment"]),
                             "có" if row["equipment_inferred"] else "", row["deadline"] or "", row["progress"],
                             row["value_text"], contact.get("name", ""), contact.get("phone", ""), contact.get("email", ""),
                             row["summary"], row["sales_note"], row["score"], row["state_label"], row["note"],
                             " ".join(s["url"] for s in row["sources"]), _day(row["published_at"]), _day(row["first_seen"])])
    else:
        writer.writerow(["Họ & tên", "Chức danh", "Công ty / Nhà máy", "Ngành", "Trạng thái nhà máy", "Nhóm",
                         "Địa bàn", "LinkedIn", "Email", "SĐT", "Gợi ý tiếp cận", "Cơ hội", "Trạng thái", "Ghi chú",
                         "Agent tìm thấy"])
        for row in list_people({"limit": config.MAX_LIST})["items"]:
            writer.writerow([row["name"], row["title"], row["company"], row["industry_label"],
                             config.PLANT_STATUS.get(row["plant_status"], ""), row["role_label"],
                             row["province"] or row["location"], row["linkedin_url"], row["email"], row["phone"],
                             row["sales_note"], row["opportunity_company"], row["state_label"], row["note"],
                             _day(row["first_seen"])])
    return "﻿" + out.getvalue()  # BOM: Excel opens Vietnamese correctly


def _day(epoch: int | None) -> str:
    if not epoch:
        return ""
    return datetime.fromtimestamp(epoch, timezone(timedelta(hours=7))).strftime("%d/%m/%Y")


# ---------------------------------------------------------------- agent config


def agent_config() -> dict:
    """What the skill needs to run: the Apify key, settings, the LLM to extract with, and the lists."""
    from .. import hermes_llm

    settings = get_settings()
    try:
        llm = hermes_llm.resolve()
        if settings.get("llm_model"):
            llm = {**llm, "model": settings["llm_model"]}
    except Exception as error:  # noqa: BLE001 - shown to the agent as is
        llm = {"error": str(error)}
    return {
        "apify_key": apify_key(),
        "apify": key_status(),
        "month_cost_usd": month_cost(),
        "settings": settings,
        "llm": llm,
        "industries": config.INDUSTRIES,
        "kinds": config.KINDS,
        "plant_status": config.PLANT_STATUS,
        "role_groups": config.ROLE_GROUPS,
        "provinces": config.PROVINCES,
        "other_provinces": config.OTHER_PROVINCES,
        "page": config.BASE_PATH,
    }
