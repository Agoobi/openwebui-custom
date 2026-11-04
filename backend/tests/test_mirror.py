"""Calendar mirror against a copy of the real Open WebUI database (skipped where Open WebUI is not installed)."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from cqf_openwebui.lich import config, db, mirror, service, timeutil
from cqf_openwebui.lich.service import Actor

REAL_OWUI = Path("/opt/open-webui/data/webui.db")
pytestmark = pytest.mark.skipif(not REAL_OWUI.exists(), reason="no Open WebUI here")


@pytest.fixture
def owui(tmp_path, monkeypatch, fresh):
    copy = tmp_path / "webui.db"
    source = sqlite3.connect(REAL_OWUI)
    target = sqlite3.connect(copy)
    source.backup(target)
    source.close()
    user_id = target.execute("SELECT id FROM user LIMIT 1").fetchone()[0]
    target.close()
    monkeypatch.setattr(config, "OWUI_DB", copy)
    with db.tx() as conn:
        conn.execute("DELETE FROM calendars")
        conn.execute("UPDATE sites SET user_id=?", (user_id,))
    conn = sqlite3.connect(copy)
    conn.row_factory = sqlite3.Row
    return conn, Actor(user_id, "Người duyệt"), fresh


def events(conn, kind):
    return conn.execute(
        "SELECT e.* FROM calendar_event e JOIN calendar c ON c.id=e.calendar_id WHERE json_extract(c.meta,'$.lich_dang')=?",
        (kind,),
    ).fetchall()


def test_scheduled_post_and_slots_show_in_the_calendar(owui):
    conn, me, _ = owui
    post = service.create_post(me, {"title": "Bài A", "html": "<p>x</p>"})
    post = service.schedule(me, post["id"], "2026-11-05 09:00", None, None)
    mirror.sync_all()
    [event] = events(conn, "posts")
    assert event["start_at"] == timeutil.parse_moment("2026-11-05 09:00", "Asia/Ho_Chi_Minh") * mirror.NS
    assert event["title"] == "🕒 Bài A" and "/#lich-dang/post=" + post["id"] in event["description"]
    [slot] = events(conn, "slots")
    assert slot["rrule"] == "FREQ=WEEKLY;BYDAY=MO,WE,FR"
    mirror.sync_all()  # nothing changed: no duplicates
    assert len(events(conn, "posts")) == 1 and len(events(conn, "slots")) == 1


def test_moving_the_event_reschedules_the_post(owui):
    conn, me, _ = owui
    post = service.schedule(me, service.create_post(me, {"title": "B", "html": "<p>x</p>"})["id"], "2026-11-05 09:00", None, None)
    mirror.sync_all()
    later = timeutil.parse_moment("2026-11-06 14:30", "Asia/Ho_Chi_Minh")
    conn.execute("UPDATE calendar_event SET start_at=? WHERE id=?", (later * mirror.NS, db.one("SELECT owui_event_id FROM posts")[0]))
    conn.commit()
    mirror.sync_all()
    moved = service.get_post(me.user_id, post["id"])
    assert moved["publish_at"] == timeutil.iso_utc(later)
    assert moved["history"][0]["actor"] == "Lịch Open WebUI"


def test_moving_into_the_past_is_undone(owui):
    conn, me, _ = owui
    post = service.schedule(me, service.create_post(me, {"title": "C", "html": "<p>x</p>"})["id"], "2026-11-05 09:00", None, None)
    mirror.sync_all()
    event_id = db.one("SELECT owui_event_id FROM posts")[0]
    conn.execute("UPDATE calendar_event SET start_at=? WHERE id=?", ((timeutil.now() - 3600) * mirror.NS, event_id))
    conn.commit()
    mirror.sync_all()
    kept = service.get_post(me.user_id, post["id"])
    assert kept["publish_at"] == post["publish_at"]
    assert "Không đổi giờ" in kept["history"][0]["text"]
    start = conn.execute("SELECT start_at FROM calendar_event WHERE id=?", (event_id,)).fetchone()[0]
    assert start == timeutil.parse_moment("2026-11-05 09:00", "Asia/Ho_Chi_Minh") * mirror.NS


def test_deleting_the_event_cancels_the_schedule(owui):
    conn, me, _ = owui
    post = service.schedule(me, service.create_post(me, {"title": "D", "html": "<p>x</p>"})["id"], "2026-11-05 09:00", None, None)
    mirror.sync_all()
    conn.execute("DELETE FROM calendar_event WHERE id=?", (db.one("SELECT owui_event_id FROM posts")[0],))
    conn.commit()
    mirror.sync_all()
    assert service.get_post(me.user_id, post["id"])["state"] == "unscheduled"
    assert events(conn, "posts") == []


def test_cancelling_here_removes_the_event(owui):
    conn, me, _ = owui
    post = service.schedule(me, service.create_post(me, {"title": "E", "html": "<p>x</p>"})["id"], "2026-11-05 09:00", None, None)
    mirror.sync_all()
    service.unschedule(me, post["id"])
    mirror.sync_all()
    assert events(conn, "posts") == []


def test_sent_post_turns_green_and_stays_gone_once_deleted(owui):
    conn, me, (fake, clock) = owui
    post = service.schedule(me, service.create_post(me, {"title": "F", "html": "<p>x</p>"})["id"], "2026-11-04 10:05", None, None)
    mirror.sync_all()
    clock["now"] += 300
    from cqf_openwebui.lich import worker
    worker.dispatch_due()
    mirror.sync_all()
    [event] = events(conn, "posts")
    assert event["title"] == "✅ F" and event["color"] == config.STATE_COLORS["sent"] and event["location"].startswith("https://")
    conn.execute("DELETE FROM calendar_event WHERE id=?", (event["id"],))
    conn.commit()
    mirror.sync_all()
    mirror.sync_all()
    assert events(conn, "posts") == []
    assert service.get_post(me.user_id, post["id"])["state"] == "sent"


def test_changing_slots_rewrites_the_slot_events(owui):
    conn, me, _ = owui
    service.save_settings(me, {"slots": [{"days": [2, 4], "time": "19:30"}, {"days": [6], "time": "09:00"}]})
    mirror.sync_all()
    assert sorted(e["rrule"] for e in events(conn, "slots")) == ["FREQ=WEEKLY;BYDAY=SA", "FREQ=WEEKLY;BYDAY=TU,TH"]
