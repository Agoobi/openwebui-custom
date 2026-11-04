"""Core rules of Lịch đăng against a fake WordPress. Run from backend/: python -m pytest -q tests"""

import pytest

from conftest import AGENT, ME
from cqf_openwebui.lich import db, service, timeutil, worker
from cqf_openwebui.lich.service import Refused
from cqf_openwebui.lich.wordpress import WpError


def make(**extra):
    return service.create_post(ME, {"title": "Chủ doanh nghiệp đọc gì", "html": "<p>Nội dung</p>", **extra})


# Time


def test_local_time_is_read_in_the_chosen_zone():
    moment = timeutil.parse_moment("2026-11-10 08:00", "Asia/Ho_Chi_Minh")
    assert timeutil.iso_utc(moment) == "2026-11-10T01:00:00Z"
    assert timeutil.describe(moment, "Asia/Ho_Chi_Minh").startswith("08:00 Thứ 3, 10/11/2026")
    assert timeutil.iso_utc(timeutil.parse_moment("2026-11-10 08:00", "Pacific/Chatham")) == "2026-11-09T18:15:00Z"


def test_offset_in_the_value_wins_over_the_zone():
    assert timeutil.parse_moment("2026-11-10T08:00:00+07:00", "UTC") == timeutil.parse_moment("2026-11-10 01:00", "UTC")


def test_time_skipped_by_dst_is_refused():
    with pytest.raises(ValueError):
        timeutil.parse_moment("2027-03-28 02:30", "Europe/Paris")


def test_slots_follow_weekdays_in_the_zone():
    start = timeutil.parse_moment("2026-11-04 10:00", "Asia/Ho_Chi_Minh")  # a Wednesday
    found = timeutil.slot_times([{"days": [1, 3, 5], "time": "08:00"}], "Asia/Ho_Chi_Minh", start, 7)
    assert [timeutil.describe(m, "Asia/Ho_Chi_Minh")[:15] for m in found] == ["08:00 Thứ 6, 06", "08:00 Thứ 2, 09", "08:00 Thứ 4, 11"]


# Scheduling rules


def test_new_post_waits_unscheduled_with_default_mode():
    post = make()
    assert post["state"] == "unscheduled" and post["mode"] == "publish" and post["site_id"] == "s1"
    assert post["slug"] == "chu-doanh-nghiep-doc-gi"


def test_schedule_needs_two_minutes_lead():
    post = make()
    with pytest.raises(Refused):
        service.schedule(ME, post["id"], "2026-11-04 10:01", None, None)
    done = service.schedule(ME, post["id"], "2026-11-04 10:02", None, "draft")
    assert done["state"] == "scheduled" and done["mode"] == "draft"
    assert done["publish_at"] == "2026-11-04T03:02:00Z"


def test_next_slot_skips_taken_ones():
    first = service.schedule(ME, make()["id"], "next", None, None)
    second = service.schedule(ME, make()["id"], "next", None, None)
    assert first["publish_at"] == "2026-11-06T01:00:00Z"
    assert second["publish_at"] == "2026-11-09T01:00:00Z"


def test_cancel_keeps_the_post():
    post = service.schedule(ME, make()["id"], "2026-11-05 09:00", None, None)
    back = service.unschedule(ME, post["id"])
    assert back["state"] == "unscheduled" and back["publish_at"] is None and back["title"] == post["title"]


def test_agent_cannot_touch_sites_or_settings():
    with pytest.raises(Refused):
        service.save_settings(AGENT, {"default_mode": "draft"})
    with pytest.raises(Refused):
        service.delete_site(AGENT, "s1")


def test_schedule_without_a_site_is_refused():
    with db.tx() as conn:
        conn.execute("DELETE FROM sites")
    post = make()
    with pytest.raises(Refused, match="Kết nối WordPress"):
        service.schedule(ME, post["id"], "2026-11-05 09:00", None, None)


# Sending


def test_due_post_is_published(fresh):
    fake, clock = fresh
    post = service.schedule(ME, make(tags=["AI"])["id"], "2026-11-04 10:05", None, None)
    assert worker.dispatch_due() == 0
    clock["now"] += 5 * 60
    assert worker.dispatch_due() == 1
    sent = service.get_post("u1", post["id"])
    assert sent["state"] == "sent" and sent["wp_status"] == "publish" and sent["wp_url"].endswith("/chu-doanh-nghiep-doc-gi/")
    with pytest.raises(Refused):
        service.update_post(ME, post["id"], {"title": "x"})


def test_draft_mode_lands_as_wordpress_draft(fresh):
    fake, clock = fresh
    post = service.schedule(ME, make()["id"], "2026-11-04 10:05", None, "draft")
    clock["now"] += 300
    worker.dispatch_due()
    sent = service.get_post("u1", post["id"])
    assert sent["state"] == "sent" and sent["wp_status"] == "draft" and sent["wp_url"] is None


def test_network_error_retries_then_succeeds_without_a_copy(fresh):
    fake, clock = fresh
    fake.fail_after_save = True  # WordPress saved it, but the answer timed out
    post = service.schedule(ME, make()["id"], "2026-11-04 10:05", None, None)
    clock["now"] += 300
    worker.dispatch_due()
    waiting = service.get_post("u1", post["id"])
    assert waiting["state"] == "sending" and waiting["attempts"] == 1 and "40 giây" in waiting["error"]
    clock["now"] += 60
    worker.dispatch_due()
    sent = service.get_post("u1", post["id"])
    assert sent["state"] == "sent" and len(fake.posts) == 1


def test_wrong_password_fails_at_once(fresh):
    fake, clock = fresh
    fake.fail_with = WpError("Sai tên đăng nhập hoặc application password (401).", permanent=True)
    post = service.schedule(ME, make()["id"], "2026-11-04 10:05", None, None)
    clock["now"] += 300
    worker.dispatch_due()
    failed = service.get_post("u1", post["id"])
    assert failed["state"] == "failed" and "application password" in failed["error"]
    again = service.schedule(ME, post["id"], "2026-11-04 10:20", None, None)
    assert again["state"] == "scheduled" and again["error"] is None


def test_firewall_keeps_retrying_until_the_give_up_time(fresh):
    fake, clock = fresh
    fake.fail_with = WpError("Tường lửa của hosting chặn")
    post = service.schedule(ME, make()["id"], "2026-11-04 10:05", None, None)
    clock["now"] += 300
    for _ in range(40):
        worker.dispatch_due()
        clock["now"] += 600
    failed = service.get_post("u1", post["id"])
    assert failed["state"] == "failed" and failed["attempts"] > 3


def test_a_waiting_retry_can_be_cancelled(fresh):
    fake, clock = fresh
    fake.fail_with = WpError("Tường lửa của hosting chặn")
    post = service.schedule(ME, make()["id"], "2026-11-04 10:05", None, None)
    clock["now"] += 300
    worker.dispatch_due()
    assert service.unschedule(ME, post["id"])["state"] == "unscheduled"


def test_post_being_sent_is_locked():
    post = service.schedule(ME, make()["id"], "2026-11-04 10:05", None, None)
    with db.tx() as conn:
        conn.execute("UPDATE posts SET state='sending', next_try_at=NULL WHERE id=?", (post["id"],))
    with pytest.raises(Refused, match="đang được gửi"):
        service.update_post(ME, post["id"], {"title": "Khác"})
    with pytest.raises(Refused):
        service.unschedule(ME, post["id"])


def test_restart_resumes_an_interrupted_send(fresh):
    fake, clock = fresh
    post = service.schedule(ME, make()["id"], "2026-11-04 10:05", None, None)
    with db.tx() as conn:
        conn.execute("UPDATE posts SET state='sending', next_try_at=NULL WHERE id=?", (post["id"],))
    clock["now"] += 300
    worker.recover()
    worker.dispatch_due()
    assert service.get_post("u1", post["id"])["state"] == "sent"


def test_cover_must_be_an_image():
    post = make()
    with pytest.raises(Refused):
        service.set_cover(ME, post["id"], b"<?php echo 1;", "x.php", None)
    png = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"rest"
    assert service.set_cover(ME, post["id"], png, "a.png", "Ảnh")["has_cover"] is True


def test_unknown_category_fails_at_once(fresh):
    fake, clock = fresh
    post = service.schedule(ME, make(categories=["Không có"])["id"], "2026-11-04 10:05", None, None)
    clock["now"] += 300
    worker.dispatch_due()
    failed = service.get_post("u1", post["id"])
    assert failed["state"] == "failed" and "Không có" in failed["error"] and fake.saves == 0


def test_inline_images_go_up_once_and_the_html_points_at_wordpress(fresh):
    fake, clock = fresh
    png = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"rest"
    post = make(categories=["Tin tức"])
    image = service.add_media(ME, post["id"], png, "Sơ đồ phòng lab.png")
    assert image["url"].startswith("/api/v1/cqf/lich/media/" + post["id"] + "/so-do-phong-lab-")
    service.update_post(ME, post["id"], {"html": f'<p>a</p><img src="{image["url"]}" alt="x"><img src="/api/v1/cqf/lich/media/other/z.png">'})
    service.schedule(ME, post["id"], "2026-11-04 10:05", None, None)
    fake.fail_after_save = True  # first try times out after WordPress saved it
    clock["now"] += 300
    worker.dispatch_due()
    clock["now"] += 60
    worker.dispatch_due()
    sent = service.get_post("u1", post["id"])
    assert sent["state"] == "sent" and fake.uploads == [image["name"]]
    saved_html = fake.posts[sent["wp_post_id"]]["content"]
    assert f'src="https://example.test/wp-content/uploads/{image["name"]}"' in saved_html
    assert 'src="/api/v1/cqf/lich/media/other/z.png"' in saved_html  # another post's image is left alone
    assert service.media_path("u1", post["id"], image["name"]) is not None
    assert service.media_path("u1", post["id"], "../secret.key") is None
