"""Lich dang: mirror of the schedule into the Open WebUI calendar, both ways.

Each user gets a calendar "Lịch đăng bài" (one event per post) and "Khung giờ đăng" (their weekly slots).
Open WebUI keeps times in nanoseconds since the epoch. The rows are written straight into the Open WebUI
database on this machine, which works for every user without API keys.

Back from Open WebUI: an event moved to another time reschedules the post; a deleted event cancels it.
"""

import json
import logging
import sqlite3
import time
import uuid

from . import config, db, service, timeutil
from .service import Actor, Refused

log = logging.getLogger("lich.mirror")

NS = 1_000_000_000
CALENDAR_NAME = "Lịch đăng bài"
SLOTS_NAME = "Khung giờ đăng"
CALENDAR_COLOR = "#d97706"
SLOTS_COLOR = "#a3a3a3"
EVENT_MINUTES = 30
GONE = "-"  # a sent post whose event the user removed: do not bring it back
SENT_WINDOW_DAYS = 120
BYDAY = {1: "MO", 2: "TU", 3: "WE", 4: "TH", 5: "FR", 6: "SA", 7: "SU"}
REQUIRED = {
    "calendar": {"id", "user_id", "name", "color", "is_default", "data", "meta", "created_at", "updated_at"},
    "calendar_event": {"id", "calendar_id", "user_id", "title", "description", "start_at", "end_at", "all_day",
                       "rrule", "color", "location", "data", "meta", "is_cancelled", "created_at", "updated_at"},
}


def _owui() -> sqlite3.Connection:
    conn = sqlite3.connect(config.OWUI_DB, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    for table, columns in REQUIRED.items():
        have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not columns <= have:
            raise RuntimeError(f"Bảng {table} của Open WebUI đã đổi cấu trúc; tạm dừng đồng bộ lịch.")
    return conn


def _ns() -> int:
    return time.time_ns()


def _ensure_calendar(conn, user_id: str, name: str, color: str, kind: str, known: str | None) -> str:
    if known and conn.execute("SELECT 1 FROM calendar WHERE id=?", (known,)).fetchone():
        return known
    found = conn.execute(
        "SELECT id FROM calendar WHERE user_id=? AND json_extract(meta, '$.lich_dang')=?", (user_id, kind)
    ).fetchone()
    if found:
        return found["id"]
    cal_id = str(uuid.uuid4())
    stamp = _ns()
    conn.execute(
        "INSERT INTO calendar (id, user_id, name, color, is_default, data, meta, created_at, updated_at) "
        "VALUES (?,?,?,?,0,NULL,?,?,?)",
        (cal_id, user_id, name, color, json.dumps({"lich_dang": kind}), stamp, stamp),
    )
    return cal_id


def _users() -> list[str]:
    rows = db.query(
        "SELECT DISTINCT user_id FROM posts WHERE archived_at IS NULL UNION SELECT user_id FROM settings "
        "UNION SELECT user_id FROM sites"
    )
    return [r["user_id"] for r in rows]


def _event_text(post, site_name: str | None, tz: str) -> tuple[str, str, str | None]:
    state = post["state"]
    prefix = {"scheduled": "🕒", "sending": "📤", "sent": "✅", "failed": "⚠️"}[state]
    if state == "sent" and post["wp_status"] != "publish":
        prefix = "📝"
    title = f"{prefix} {post['title']}"
    lines = [
        f"Trạng thái: {config.STATE_LABELS[state]}"
        + (" (đã vào WordPress dạng nháp)" if state == "sent" and post["wp_status"] != "publish" else ""),
        f"Chế độ: {config.MODE_LABELS[post['mode']]}",
    ]
    if site_name:
        lines.append(f"Site: {site_name}")
    if post["publish_at"]:
        lines.append(f"Giờ đăng: {timeutil.describe(post['publish_at'], tz)}")
    if post["error"]:
        lines.append(f"Lỗi gần nhất: {post['error']}")
    lines.append(f"Quản lý bài: {config.BASE_PATH}/post={post['id']}")
    if state in ("scheduled", "sending"):
        lines.append("Kéo sự kiện sang giờ khác để đổi giờ đăng; xoá sự kiện để huỷ lịch.")
    location = post["wp_url"] or post["wp_edit_url"]
    return title, "\n".join(lines), location


def _sync_posts(conn, user_id: str, cal_id: str, tz: str, pending: list) -> None:
    """Event ids to remember go to pending and are saved only once the Open WebUI write has committed."""
    actor = Actor(user_id, "Lịch Open WebUI")
    sites = {r["id"]: r["name"] for r in db.query("SELECT id, name FROM sites WHERE user_id=?", (user_id,))}
    since = timeutil.now() - SENT_WINDOW_DAYS * 86400
    posts = db.query(
        "SELECT * FROM posts WHERE user_id=? AND (archived_at IS NULL OR owui_event_id IS NOT NULL)", (user_id,)
    )
    for post in posts:
        event_id = post["owui_event_id"]
        event = None
        if event_id and event_id != GONE:
            event = conn.execute("SELECT * FROM calendar_event WHERE id=?", (event_id,)).fetchone()
        wanted = (
            post["archived_at"] is None
            and post["state"] in ("scheduled", "sending", "sent", "failed")
            and post["publish_at"] is not None
            and (post["state"] != "sent" or (post["sent_at"] or 0) >= since)
        )

        # Changes made in the Open WebUI calendar come back first.
        if event_id and event_id != GONE and event is None:
            if post["state"] in ("scheduled", "failed") or (post["state"] == "sending" and post["next_try_at"]):
                try:
                    service.unschedule(actor, post["id"], "Xoá sự kiện trong Lịch Open WebUI → huỷ lịch, bài về Chưa lên lịch")
                except Refused:
                    pass
            pending.append((post["id"], GONE if post["state"] == "sent" else None, None, None))
            continue
        if event is not None and post["owui_start"] and event["start_at"] != post["owui_start"] and post["state"] == "scheduled":
            moment = event["start_at"] // NS
            try:
                service.schedule(actor, post["id"], moment, tz, None)
                post = db.one("SELECT * FROM posts WHERE id=?", (post["id"],))
            except Refused as error:
                with db.tx() as tx:
                    service._history(tx, post["id"], actor, "Không đổi giờ theo Lịch Open WebUI: " + error.message)
            event = None  # rewrite it below with the time that is actually kept

        if not wanted:
            if event is not None:
                conn.execute("DELETE FROM calendar_event WHERE id=?", (event["id"],))
            if event_id and event_id != GONE:
                pending.append((post["id"], None, None, None))
            continue
        if event_id == GONE:
            continue

        title, description, location = _event_text(post, sites.get(post["site_id"]), tz)
        start = post["publish_at"] * NS
        color = config.STATE_COLORS[post["state"]]
        sig = json.dumps([title, description, location, start, color], ensure_ascii=False)
        if event is not None and post["owui_sig"] == sig:
            continue
        stamp = _ns()
        values = (title, description, start, start + EVENT_MINUTES * 60 * NS, color, location,
                  json.dumps({"lich_dang_post": post["id"]}), stamp)
        if event is not None or (event_id and event_id != GONE and conn.execute(
                "SELECT 1 FROM calendar_event WHERE id=?", (event_id,)).fetchone()):
            conn.execute(
                "UPDATE calendar_event SET title=?, description=?, start_at=?, end_at=?, color=?, location=?, data=?, "
                "updated_at=?, is_cancelled=0 WHERE id=?",
                (*values, event_id),
            )
        else:
            event_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO calendar_event (id, calendar_id, user_id, title, description, start_at, end_at, all_day, "
                "rrule, color, location, data, meta, is_cancelled, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,0,NULL,?,?,?,?,0,?,?)",
                (event_id, cal_id, user_id, title, description, start, start + EVENT_MINUTES * 60 * NS, color,
                 location, values[6], json.dumps({"lich_dang": "post"}), stamp, stamp),
            )
        pending.append((post["id"], event_id, start, sig))


def _save_events(pending: list) -> None:
    with db.tx() as tx:
        for post_id, event_id, start, sig in pending:
            tx.execute("UPDATE posts SET owui_event_id=?, owui_start=?, owui_sig=? WHERE id=?", (event_id, start, sig, post_id))


def _sync_slots(conn, user_id: str, cal_id: str, settings: dict, known_sig: str | None) -> str:
    sig = json.dumps([settings["slots"], settings["timezone"]])
    if sig == known_sig:
        return sig
    conn.execute("DELETE FROM calendar_event WHERE calendar_id=?", (cal_id,))
    tz = settings["timezone"]
    for slot in settings["slots"]:
        first = timeutil.slot_times([slot], tz, timeutil.now() - 7 * 86400, 7)
        if not first:
            continue
        start = first[0] * NS
        stamp = _ns()
        conn.execute(
            "INSERT INTO calendar_event (id, calendar_id, user_id, title, description, start_at, end_at, all_day, rrule, "
            "color, location, data, meta, is_cancelled, created_at, updated_at) VALUES (?,?,?,?,?,?,?,0,?,?,NULL,NULL,?,0,?,?)",
            (str(uuid.uuid4()), cal_id, user_id, f"⭐ Khung giờ đăng {slot['time']}",
             f"Giờ đăng quen thuộc ({tz}). Agent và nút \"Giờ trống kế tiếp\" chọn giờ trong các khung này. "
             f"Đổi trong Lịch đăng → Cài đặt.",
             start, start + 15 * 60 * NS, "FREQ=WEEKLY;BYDAY=" + ",".join(BYDAY[d] for d in slot["days"]),
             SLOTS_COLOR, json.dumps({"lich_dang": "slot"}), stamp, stamp),
        )
    return sig


def sync_all() -> None:
    if config.OWUI_DB is None or not config.OWUI_DB.exists():
        return
    conn = _owui()
    try:
        for user_id in _users():
            if not conn.execute("SELECT 1 FROM user WHERE id=?", (user_id,)).fetchone():
                continue
            settings = service.get_settings(user_id)
            known = db.one("SELECT * FROM calendars WHERE user_id=?", (user_id,))
            pending: list = []
            conn.execute("BEGIN IMMEDIATE")
            try:
                cal_id = _ensure_calendar(conn, user_id, CALENDAR_NAME, CALENDAR_COLOR, "posts",
                                          known["owui_calendar_id"] if known else None)
                slots_id = _ensure_calendar(conn, user_id, SLOTS_NAME, SLOTS_COLOR, "slots",
                                            known["slots_calendar_id"] if known else None)
                slots_sig = _sync_slots(conn, user_id, slots_id, settings,
                                        known["slots_sig"] if known and known["slots_calendar_id"] == slots_id else None)
                _sync_posts(conn, user_id, cal_id, settings["timezone"], pending)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            _save_events(pending)
            with db.tx() as tx:
                tx.execute(
                    "INSERT INTO calendars (user_id, owui_calendar_id, slots_calendar_id, slots_sig) VALUES (?,?,?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET owui_calendar_id=excluded.owui_calendar_id, "
                    "slots_calendar_id=excluded.slots_calendar_id, slots_sig=excluded.slots_sig",
                    (user_id, cal_id, slots_id, slots_sig),
                )
    finally:
        conn.close()
