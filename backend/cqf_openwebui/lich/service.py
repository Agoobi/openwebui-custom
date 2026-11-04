"""What can happen to a post, a site and the settings. API, agent and worker all go through here."""

import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from . import config, db, timeutil
from .secrets_box import open_secret, seal
from .wordpress import WordPress, WpError, normalize_url


class Refused(HTTPException):
    """An action that is not allowed; the message is shown to the person as is (FastAPI answers it directly)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(status_code=status, detail=message)
        self.message = message
        self.status = status


@dataclass
class Actor:
    user_id: str
    name: str
    is_agent: bool = False
    role: str = ""


# Settings


def get_settings(user_id: str) -> dict:
    row = db.one("SELECT data FROM settings WHERE user_id = ?", (user_id,))
    data = {**config.DEFAULT_SETTINGS, **db.loads(row["data"] if row else None, {})}
    sites = list_sites(user_id)
    if data.get("default_site_id") not in {s["id"] for s in sites}:
        data["default_site_id"] = sites[0]["id"] if sites else None
    return data


def save_settings(actor: Actor, changes: dict) -> dict:
    if actor.is_agent:
        raise Refused(config.RULE_TEXT["agent"], 403)
    current = get_settings(actor.user_id)
    if "timezone" in changes:
        if not timeutil.valid_zone(str(changes["timezone"])):
            raise Refused(f"Múi giờ không hợp lệ: {changes['timezone']}")
        current["timezone"] = str(changes["timezone"])
    if "default_mode" in changes:
        if changes["default_mode"] not in config.MODES:
            raise Refused("Chế độ đăng phải là publish hoặc draft.")
        current["default_mode"] = changes["default_mode"]
    if "default_site_id" in changes:
        if changes["default_site_id"] and not _site_row(actor.user_id, changes["default_site_id"]):
            raise Refused("Không thấy site này.", 404)
        current["default_site_id"] = changes["default_site_id"]
    if "slots" in changes:
        current["slots"] = _clean_slots(changes["slots"])
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO settings (user_id, data) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET data = excluded.data",
            (actor.user_id, db.dumps(current)),
        )
    return get_settings(actor.user_id)


def _clean_slots(slots) -> list[dict]:
    if not isinstance(slots, list) or len(slots) > 30:
        raise Refused("Khung giờ đăng không hợp lệ.")
    clean = []
    for slot in slots:
        days = sorted({int(d) for d in slot.get("days", []) if 1 <= int(d) <= 7})
        time_text = str(slot.get("time", ""))
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time_text):
            raise Refused(f"Giờ {time_text} không hợp lệ, dùng dạng 08:00.")
        if not days:
            raise Refused("Mỗi khung giờ cần ít nhất một ngày trong tuần.")
        clean.append({"days": days, "time": time_text})
    return clean


# Sites


def _site_public(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "url": row["url"],
        "username": row["username"],
        "site_timezone": row["site_timezone"],
        "unfiltered_html": None if row["can_unfiltered_html"] is None else bool(row["can_unfiltered_html"]),
        "checked_at": timeutil.iso_utc(row["checked_at"]),
        "check_ok": None if row["check_ok"] is None else bool(row["check_ok"]),
        "check_error": row["check_error"],
    }


def _site_row(user_id: str, site_id: str):
    return db.one("SELECT * FROM sites WHERE id = ? AND user_id = ?", (site_id, user_id))


def list_sites(user_id: str) -> list[dict]:
    return [_site_public(r) for r in db.query("SELECT * FROM sites WHERE user_id = ? ORDER BY created_at", (user_id,))]


def client_for(site_row) -> WordPress:
    return WordPress(site_row["url"], site_row["username"], open_secret(site_row["secret"]))


def save_site(actor: Actor, site_id: str | None, data: dict) -> dict:
    """Checks the connection first; a site is only saved when WordPress accepts the password and rights."""
    if actor.is_agent:
        raise Refused(config.RULE_TEXT["agent"], 403)
    existing = _site_row(actor.user_id, site_id) if site_id else None
    if site_id and not existing:
        raise Refused("Không thấy site này.", 404)
    try:
        url = normalize_url(str(data.get("url") or (existing["url"] if existing else "")))
    except WpError as error:
        raise Refused(error.message) from error
    username = str(data.get("username") or (existing["username"] if existing else "")).strip()
    password = str(data.get("app_password") or "").strip()
    if not password and existing:
        password = open_secret(existing["secret"])
    if not username or not password:
        raise Refused("Cần tên đăng nhập và application password.")
    name = str(data.get("name") or (existing["name"] if existing else "") or url.split("//", 1)[1]).strip()

    # A wrong password or missing rights is refused. A site that cannot be reached right now (firewall,
    # downtime) is saved with the reason, so the owner can fix the network side and press Check again.
    info = None
    reach_error = None
    try:
        with WordPress(url, username, password) as wp:
            info = wp.check()
    except WpError as error:
        if error.permanent:
            raise Refused(error.message, 422) from error
        reach_error = error.message

    stamp = timeutil.now()
    tz = info["timezone"] if info else None
    unfiltered = int(info["unfiltered_html"]) if info else None
    ok = 0 if reach_error else 1
    with db.tx() as conn:
        if existing:
            conn.execute(
                "UPDATE sites SET name=?, url=?, username=?, secret=?, site_timezone=COALESCE(?, site_timezone), "
                "can_unfiltered_html=COALESCE(?, can_unfiltered_html), checked_at=?, check_ok=?, check_error=?, "
                "updated_at=? WHERE id=?",
                (name, url, username, seal(password), tz, unfiltered, stamp, ok, reach_error, stamp, site_id),
            )
        else:
            site_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO sites (id, user_id, name, url, username, secret, site_timezone, can_unfiltered_html, "
                "checked_at, check_ok, check_error, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (site_id, actor.user_id, name, url, username, seal(password), tz, unfiltered, stamp, ok,
                 reach_error, stamp, stamp),
            )
    result = _site_public(_site_row(actor.user_id, site_id))
    if info:
        result.update(account=info["user"], roles=info["roles"])
    return result


def check_site(actor: Actor, site_id: str) -> dict:
    row = _site_row(actor.user_id, site_id)
    if not row:
        raise Refused("Không thấy site này.", 404)
    error_text = None
    info = None
    try:
        with client_for(row) as wp:
            info = wp.check()
    except (WpError, RuntimeError) as error:
        error_text = getattr(error, "message", str(error))
    with db.tx() as conn:
        conn.execute(
            "UPDATE sites SET checked_at=?, check_ok=?, check_error=?, site_timezone=COALESCE(?, site_timezone), "
            "can_unfiltered_html=COALESCE(?, can_unfiltered_html) WHERE id=?",
            (timeutil.now(), 0 if error_text else 1, error_text, info and info["timezone"],
             None if info is None else int(info["unfiltered_html"]), site_id),
        )
    result = _site_public(_site_row(actor.user_id, site_id))
    if info:
        result.update(account=info["user"], roles=info["roles"])
    return result


def delete_site(actor: Actor, site_id: str) -> None:
    if actor.is_agent:
        raise Refused(config.RULE_TEXT["agent"], 403)
    if not _site_row(actor.user_id, site_id):
        raise Refused("Không thấy site này.", 404)
    waiting = db.one(
        "SELECT COUNT(*) AS n FROM posts WHERE site_id=? AND state IN ('scheduled','sending') AND archived_at IS NULL",
        (site_id,),
    )["n"]
    if waiting:
        raise Refused(f"Còn {waiting} bài đang hẹn đăng lên site này. Huỷ lịch hoặc chuyển site cho các bài đó trước.")
    with db.tx() as conn:
        conn.execute("UPDATE posts SET site_id=NULL WHERE site_id=? AND state IN ('unscheduled','failed')", (site_id,))
        conn.execute("DELETE FROM sites WHERE id=?", (site_id,))


# Posts


def slugify(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:90].strip("-") or uuid.uuid4().hex[:8]


def _history(conn, post_id: str, actor: Actor | str, text: str) -> None:
    name = actor if isinstance(actor, str) else actor.name
    conn.execute("INSERT INTO history (post_id, at, actor, text) VALUES (?,?,?,?)", (post_id, timeutil.now(), name, text))


def _row(user_id: str, post_id: str):
    row = db.one("SELECT * FROM posts WHERE id=? AND user_id=? AND archived_at IS NULL", (post_id, user_id))
    if not row:
        raise Refused("Không thấy bài này.", 404)
    return row


def post_public(row, with_body: bool = False) -> dict:
    data = {
        "id": row["id"],
        "title": row["title"],
        "excerpt": row["excerpt"],
        "slug": row["slug"],
        "categories": db.loads(row["categories"], []),
        "tags": db.loads(row["tags"], []),
        "has_cover": bool(row["cover_file"]),
        "cover_alt": row["cover_alt"],
        "state": row["state"],
        "state_label": config.STATE_LABELS[row["state"]],
        "mode": row["mode"],
        "mode_label": config.MODE_LABELS[row["mode"]],
        "site_id": row["site_id"],
        "publish_at": timeutil.iso_utc(row["publish_at"]),
        "attempts": row["attempts"],
        "next_try_at": timeutil.iso_utc(row["next_try_at"]),
        "wp_post_id": row["wp_post_id"],
        "wp_status": row["wp_status"],
        "wp_url": row["wp_url"],
        "wp_edit_url": row["wp_edit_url"],
        "sent_at": timeutil.iso_utc(row["sent_at"]),
        "error": row["error"],
        "source": row["source"],
        "words": len(re.sub(r"<[^>]+>", " ", row["html"]).split()),
        "created_at": timeutil.iso_utc(row["created_at"]),
        "updated_at": timeutil.iso_utc(row["updated_at"]),
    }
    if with_body:
        data["html"] = row["html"]
        data["history"] = [
            {"at": timeutil.iso_utc(h["at"]), "actor": h["actor"], "text": h["text"]}
            for h in db.query("SELECT * FROM history WHERE post_id=? ORDER BY at DESC, id DESC LIMIT 50", (row["id"],))
        ]
    return data


def list_posts(user_id: str, start: int | None, end: int | None, state: str | None) -> list[dict]:
    sql = "SELECT * FROM posts WHERE user_id=? AND archived_at IS NULL"
    params: list = [user_id]
    if state:
        sql += " AND state=?"
        params.append(state)
    if start is not None and end is not None:
        # Unscheduled posts have no time and are always listed.
        sql += " AND (publish_at IS NULL OR (publish_at >= ? AND publish_at < ?))"
        params += [start, end]
    sql += " ORDER BY COALESCE(publish_at, 9999999999), created_at DESC"
    return [post_public(r) for r in db.query(sql, tuple(params))]


def get_post(user_id: str, post_id: str) -> dict:
    return post_public(_row(user_id, post_id), with_body=True)


def _clean_fields(data: dict) -> dict:
    clean: dict = {}
    if "title" in data:
        title = str(data["title"] or "").strip()
        if not title:
            raise Refused("Bài cần tiêu đề.")
        clean["title"] = title[:300]
    if "html" in data:
        body = str(data["html"] or "")
        if len(body.encode()) > config.MAX_HTML_BYTES:
            raise Refused("Nội dung quá dài (tối đa 2 MB).")
        clean["html"] = body
    if "excerpt" in data:
        clean["excerpt"] = str(data["excerpt"] or "").strip()[:1000]
    if "slug" in data:
        clean["slug"] = slugify(str(data["slug"])) if data["slug"] else ""
    for key in ("categories", "tags"):
        if key in data:
            values = data[key] or []
            if isinstance(values, str):
                values = values.split(",")
            clean[key] = db.dumps([str(v).strip() for v in values if str(v).strip()][:20])
    if "cover_alt" in data:
        clean["cover_alt"] = str(data["cover_alt"] or "").strip()[:300]
    return clean


def _editable(row) -> None:
    """Sent posts are final; a post is locked only while a send is running (a retry that waits is editable)."""
    if row["state"] == "sending" and row["next_try_at"] is None:
        raise Refused("Bài đang được gửi lên WordPress, đợi xong rồi hãy sửa.", 409)
    if row["state"] == "sent":
        raise Refused(config.RULE_TEXT["sent"], 409)


def create_post(actor: Actor, data: dict) -> dict:
    fields = _clean_fields(data)
    if "title" not in fields:
        raise Refused("Bài cần tiêu đề.")
    settings = get_settings(actor.user_id)
    mode = data.get("mode") or settings["default_mode"]
    if mode not in config.MODES:
        raise Refused("Chế độ đăng phải là publish hoặc draft.")
    site_id = data.get("site_id") or settings["default_site_id"]
    if site_id and not _site_row(actor.user_id, site_id):
        raise Refused("Không thấy site này.", 404)
    post_id = uuid.uuid4().hex[:12]
    stamp = timeutil.now()
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO posts (id, user_id, site_id, title, html, excerpt, slug, categories, tags, cover_alt, state, "
            "mode, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?, 'unscheduled', ?,?,?,?)",
            (post_id, actor.user_id, site_id, fields["title"], fields.get("html", ""), fields.get("excerpt", ""),
             fields.get("slug") or slugify(fields["title"]), fields.get("categories", "[]"), fields.get("tags", "[]"),
             fields.get("cover_alt", ""), mode, "agent" if actor.is_agent else "web", stamp, stamp),
        )
        _history(conn, post_id, actor, "Tạo bài")
    if data.get("publish_at"):
        return schedule(actor, post_id, data["publish_at"], data.get("timezone"), None)
    return get_post(actor.user_id, post_id)


def update_post(actor: Actor, post_id: str, data: dict) -> dict:
    row = _row(actor.user_id, post_id)
    _editable(row)
    fields = _clean_fields(data)
    if "site_id" in data:
        if data["site_id"] and not _site_row(actor.user_id, data["site_id"]):
            raise Refused("Không thấy site này.", 404)
        if row["wp_post_id"] and data["site_id"] != row["site_id"]:
            raise Refused("Bài đã có trên một site WordPress, không chuyển sang site khác được.")
        fields["site_id"] = data["site_id"] or None
    if not fields:
        return get_post(actor.user_id, post_id)
    changed = [k for k in fields if str(fields[k]) != str(row[k])]
    if not changed:
        return get_post(actor.user_id, post_id)
    with db.tx() as conn:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE posts SET {sets}, updated_at=? WHERE id=?", (*fields.values(), timeutil.now(), post_id))
        names = {"title": "tiêu đề", "html": "nội dung", "excerpt": "mô tả ngắn", "slug": "đường dẫn",
                 "categories": "chuyên mục", "tags": "thẻ", "cover_alt": "chú thích ảnh", "site_id": "site"}
        _history(conn, post_id, actor, "Sửa " + ", ".join(names.get(k, k) for k in changed))
    return get_post(actor.user_id, post_id)


def set_cover(actor: Actor, post_id: str, content: bytes, filename: str, alt: str | None) -> dict:
    row = _row(actor.user_id, post_id)
    _editable(row)
    if len(content) > config.MAX_COVER_BYTES:
        raise Refused("Ảnh bìa quá lớn (tối đa 8 MB).")
    kind = _image_kind(content)
    if kind not in ("jpeg", "png", "gif", "webp"):
        raise Refused("Ảnh bìa phải là JPG, PNG, GIF hoặc WebP.")
    extension = "jpg" if kind == "jpeg" else kind
    name = f"{post_id}-{uuid.uuid4().hex[:6]}.{extension}"
    (config.COVER_DIR / name).write_bytes(content)
    old = row["cover_file"]
    with db.tx() as conn:
        conn.execute(
            "UPDATE posts SET cover_file=?, cover_alt=COALESCE(?, cover_alt), wp_media_id=NULL, updated_at=? WHERE id=?",
            (name, alt, timeutil.now(), post_id),
        )
        _history(conn, post_id, actor, "Đổi ảnh bìa" if old else "Thêm ảnh bìa")
    if old:
        (config.COVER_DIR / old).unlink(missing_ok=True)
    return get_post(actor.user_id, post_id)


def _image_kind(content: bytes) -> str | None:
    if content[:3] == bytes([0xFF, 0xD8, 0xFF]):
        return "jpeg"
    if content[:8] == bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]):
        return "png"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    return None


def remove_cover(actor: Actor, post_id: str) -> dict:
    row = _row(actor.user_id, post_id)
    _editable(row)
    if row["cover_file"]:
        with db.tx() as conn:
            conn.execute("UPDATE posts SET cover_file=NULL, wp_media_id=NULL, updated_at=? WHERE id=?", (timeutil.now(), post_id))
            _history(conn, post_id, actor, "Bỏ ảnh bìa")
        (config.COVER_DIR / row["cover_file"]).unlink(missing_ok=True)
    return get_post(actor.user_id, post_id)


def cover_path(user_id: str, post_id: str) -> Path | None:
    row = _row(user_id, post_id)
    return config.COVER_DIR / row["cover_file"] if row["cover_file"] else None


def _resolve_time(user_id: str, value, tz_name: str | None) -> int:
    tz = tz_name or get_settings(user_id)["timezone"]
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return timeutil.parse_moment(str(value), tz)
    except ValueError as error:
        raise Refused(str(error)) from error


def schedule(actor: Actor, post_id: str, when, tz_name: str | None, mode: str | None) -> dict:
    row = _row(actor.user_id, post_id)
    _editable(row)
    settings = get_settings(actor.user_id)
    tz = tz_name or settings["timezone"]
    moment = _resolve_time(actor.user_id, when, tz) if when not in (None, "", "next") else next_free_slot(actor.user_id)
    if moment is None:
        raise Refused("Chưa có khung giờ đăng nào còn trống; đặt khung giờ trong Cài đặt hoặc chọn giờ cụ thể.")
    if moment < timeutil.now() + config.MIN_LEAD_SECONDS:
        raise Refused(config.RULE_TEXT["lead"] + f" (Giờ bạn chọn: {timeutil.describe(moment, tz)}.)")
    new_mode = mode or row["mode"]
    if new_mode not in config.MODES:
        raise Refused("Chế độ đăng phải là publish hoặc draft.")
    site_id = row["site_id"] or settings["default_site_id"]
    if not site_id:
        raise Refused("Chưa có site WordPress nào. Vào Cài đặt → Kết nối WordPress để thêm site trước.")
    if not row["html"].strip():
        raise Refused("Bài chưa có nội dung.")
    with db.tx() as conn:
        changed = conn.execute(
            "UPDATE posts SET state='scheduled', publish_at=?, mode=?, site_id=?, attempts=0, next_try_at=NULL, "
            "error=NULL, updated_at=? WHERE id=? AND NOT (state='sending' AND next_try_at IS NULL) AND state<>'sent'",
            (moment, new_mode, site_id, timeutil.now(), post_id),
        ).rowcount
        if changed == 0:
            raise Refused("Bài vừa bắt đầu được gửi lên WordPress, không đổi được nữa.", 409)
        verb = "Đổi giờ đăng" if row["state"] == "scheduled" else "Lên lịch"
        _history(conn, post_id, actor, f"{verb}: {timeutil.describe(moment, tz)} · {config.MODE_LABELS[new_mode]}")
    return get_post(actor.user_id, post_id)


def set_mode(actor: Actor, post_id: str, mode: str) -> dict:
    row = _row(actor.user_id, post_id)
    _editable(row)
    if mode not in config.MODES:
        raise Refused("Chế độ đăng phải là publish hoặc draft.")
    if mode != row["mode"]:
        with db.tx() as conn:
            conn.execute("UPDATE posts SET mode=?, updated_at=? WHERE id=?", (mode, timeutil.now(), post_id))
            _history(conn, post_id, actor, "Đổi chế độ: " + config.MODE_LABELS[mode])
    return get_post(actor.user_id, post_id)


def unschedule(actor: Actor, post_id: str, note: str = "Huỷ lịch, bài về Chưa lên lịch") -> dict:
    row = _row(actor.user_id, post_id)
    _editable(row)
    if row["state"] in ("scheduled", "failed", "sending"):
        with db.tx() as conn:
            changed = conn.execute(
                "UPDATE posts SET state='unscheduled', publish_at=NULL, attempts=0, next_try_at=NULL, error=NULL, "
                "updated_at=? WHERE id=? AND NOT (state='sending' AND next_try_at IS NULL) AND state<>'sent'",
                (timeutil.now(), post_id),
            ).rowcount
            if changed == 0:
                raise Refused("Bài vừa bắt đầu được gửi lên WordPress, không huỷ được nữa.", 409)
            _history(conn, post_id, actor, note)
    return get_post(actor.user_id, post_id)


def archive(actor: Actor, post_id: str) -> None:
    row = _row(actor.user_id, post_id)
    if row["state"] in ("scheduled", "sending"):
        raise Refused("Bài đang hẹn đăng; huỷ lịch trước rồi mới bỏ khỏi danh sách.", 409)
    with db.tx() as conn:
        conn.execute("UPDATE posts SET archived_at=?, updated_at=? WHERE id=?", (timeutil.now(), timeutil.now(), post_id))
        _history(conn, post_id, actor, "Bỏ khỏi Lịch đăng")


def next_free_slots(user_id: str, count: int = 5) -> list[int]:
    settings = get_settings(user_id)
    start = timeutil.now() + config.MIN_LEAD_SECONDS
    taken = [
        r["publish_at"]
        for r in db.query(
            "SELECT publish_at FROM posts WHERE user_id=? AND archived_at IS NULL AND publish_at IS NOT NULL "
            "AND state IN ('scheduled','sending','sent')",
            (user_id,),
        )
    ]
    free = []
    for moment in timeutil.slot_times(settings["slots"], settings["timezone"], start, config.SLOT_LOOKAHEAD_DAYS):
        if all(abs(moment - other) >= config.SLOT_GAP_SECONDS for other in taken):
            free.append(moment)
            if len(free) >= count:
                break
    return free


def next_free_slot(user_id: str) -> int | None:
    slots = next_free_slots(user_id, 1)
    return slots[0] if slots else None


# Sending (called by the worker)


def send(post_id: str) -> None:
    """Pushes one claimed post to WordPress. Raises WpError on failure; the worker decides on retries."""
    row = db.one("SELECT * FROM posts WHERE id=?", (post_id,))
    site = db.one("SELECT * FROM sites WHERE id=?", (row["site_id"],)) if row["site_id"] else None
    if site is None:
        raise WpError("Site WordPress của bài đã bị xoá khỏi Cài đặt.", permanent=True)

    try:
        wp = client_for(site)
    except RuntimeError as error:
        raise WpError(str(error), permanent=True) from error

    with wp:
        wp_id = row["wp_post_id"]
        if wp_id and wp.get_post(wp_id) is None:
            wp_id = None
        if not wp_id and row["attempts"] > 0:
            # A previous try may have reached WordPress before timing out: reuse that post, never make a copy.
            same = wp.find_by_slug(row["slug"])
            if same and same.get("title", {}).get("raw", "") == row["title"]:
                wp_id = int(same["id"])

        media_id = row["wp_media_id"]
        if row["cover_file"] and not media_id:
            path = config.COVER_DIR / row["cover_file"]
            if path.exists():
                media_id = wp.upload_media(path, f"{row['slug'][:60]}{path.suffix}", row["cover_alt"] or row["title"])
                with db.tx() as conn:
                    conn.execute("UPDATE posts SET wp_media_id=? WHERE id=?", (media_id, post_id))

        payload = {
            "title": row["title"],
            "content": row["html"],
            "excerpt": row["excerpt"],
            "slug": row["slug"],
            "status": "publish" if row["mode"] == "publish" else "draft",
        }
        if media_id:
            payload["featured_media"] = media_id
        categories = db.loads(row["categories"], [])
        tags = db.loads(row["tags"], [])
        if categories:
            payload["categories"] = wp.term_ids("categories", categories)
        if tags:
            payload["tags"] = wp.term_ids("tags", tags)

        saved = wp.save_post(wp_id, payload)

    wp_status = saved.get("status")
    link = saved.get("link") if wp_status == "publish" else None
    edit_url = f"{wp.url}/wp-admin/post.php?post={saved['id']}&action=edit"
    stamp = timeutil.now()
    with db.tx() as conn:
        conn.execute(
            "UPDATE posts SET state='sent', wp_post_id=?, wp_status=?, wp_url=?, wp_edit_url=?, sent_at=?, error=NULL, "
            "next_try_at=NULL, updated_at=? WHERE id=?",
            (int(saved["id"]), wp_status, link, edit_url, stamp, stamp, post_id),
        )
        if wp_status == "publish":
            _history(conn, post_id, "Máy chủ", f"Đã đăng lên {site['name']}: {link}")
        else:
            _history(conn, post_id, "Máy chủ", f"Đã lưu nháp trên {site['name']} (bài #{saved['id']}), chờ bạn bấm Đăng")
