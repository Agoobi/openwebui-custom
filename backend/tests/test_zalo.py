"""Lich dang: the Zalo OA channel against a fake Zalo API."""

import io
import urllib.parse

import pytest

from conftest import AGENT, ME
from cqf_openwebui.lich import config, db, service, timeutil, worker, zalo_oa
from cqf_openwebui.lich.service import Refused
from cqf_openwebui.lich.wordpress import WpError

PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"rest"


class FakeZalo:
    def __init__(self):
        self.created: list[dict] = []
        self.pending = 0  # verify answers "still working" this many times
        self.fail: WpError | None = None
        self.status = {}

    def __call__(self, oa_id):
        self.oa_id = oa_id
        return self

    def check(self):
        if self.fail:
            raise self.fail
        return {"ok": True}

    def create(self, article):
        if self.fail:
            raise self.fail
        self.created.append(article)
        return f"tok{len(self.created)}"

    def verify(self, token):
        if self.pending:
            self.pending -= 1
            return None
        article_id = "a" + token[3:]
        self.status[article_id] = self.created[int(token[3:]) - 1]["status"]
        return article_id

    def detail(self, article_id):
        return {"status": self.status[article_id], "link": f"https://zalo.me/article/{article_id}"}


@pytest.fixture
def zalo(fresh, monkeypatch):
    fake = FakeZalo()
    monkeypatch.setattr(zalo_oa, "Client", fake)
    monkeypatch.setattr(zalo_oa, "connected_oas", lambda: [{"oa_id": "999", "name": "Duc Duong SCI"}])
    monkeypatch.setattr(config, "PUBLIC_URL", "https://owui.example")
    site = service.add_zalo_site(ME, "999", None, None)
    return fake, fresh[1], site


def zalo_post(site, **extra):
    post = service.create_post(ME, {"title": "Ưu đãi hiệu chuẩn tháng 11", "excerpt": "Giảm 10% phí hiệu chuẩn",
                                    "html": "<h2>Ưu đãi</h2><p>Đặt lịch <strong>sớm</strong>.</p><ul><li>Một</li><li>Hai</li></ul>",
                                    "site_id": site["id"], **extra})
    service.set_cover(ME, post["id"], PNG, "bia.png", "Ảnh bìa")
    return post


def test_html_becomes_plain_zalo_blocks():
    blocks = zalo_oa.html_to_blocks(
        '<h2>Mục một</h2><p>Chữ <strong>đậm</strong> &amp; <a href="https://x.vn">link</a></p>'
        '<ol><li>Một</li><li>Hai</li></ol><ul><li>Ba</li></ul><img src="https://x.vn/a.png" alt="A"><blockquote>Trích</blockquote>')
    assert blocks == [
        {"type": "text", "content": "MỤC MỘT"},
        {"type": "text", "content": "Chữ đậm &amp; link (https://x.vn)"},
        {"type": "text", "content": "1. Một"},
        {"type": "text", "content": "2. Hai"},
        {"type": "text", "content": "• Ba"},
        {"type": "image", "url": "https://x.vn/a.png", "caption": "A"},
        {"type": "text", "content": "“Trích”"},
    ]


def test_oa_is_added_from_the_shared_token_store(zalo):
    _, _, site = zalo
    assert site["kind"] == "zalo_oa" and site["oa_id"] == "999" and site["check_ok"] is True
    assert site["options"] == {"author": "Duc Duong SCI", "comment": "show"}
    assert service.zalo_candidates(ME) == [{"oa_id": "999", "name": "Duc Duong SCI", "added": True}]
    with pytest.raises(Refused):
        service.add_zalo_site(ME, "999", None, None)
    with pytest.raises(Refused):
        service.add_zalo_site(AGENT, "999", None, None)


def test_zalo_needs_a_cover_and_short_texts(zalo):
    _, _, site = zalo
    post = service.create_post(ME, {"title": "x" * 151, "excerpt": "y" * 301, "html": "<p>a</p>", "site_id": site["id"]})
    with pytest.raises(Refused) as error:
        service.schedule(ME, post["id"], "2026-11-05 09:00", None, None)
    assert "tiêu đề 151" in error.value.message and "mô tả ngắn 301" in error.value.message and "ảnh bìa" in error.value.message


def test_mode_labels_follow_the_channel(zalo):
    _, _, site = zalo
    post = zalo_post(site)
    assert post["channel"] == "zalo_oa" and post["mode_label"] == "Hiện ngay trên Zalo OA"
    assert service.set_mode(ME, post["id"], "draft")["mode_label"] == "Tạo bài ẩn trên Zalo OA"


def test_shown_article_goes_out_at_its_time(zalo):
    fake, clock, site = zalo
    post = zalo_post(site)
    image = service.add_media(ME, post["id"], PNG, "so do.png")
    service.update_post(ME, post["id"], {"html": f'<p>Chào</p><img src="{image["url"]}" alt="Sơ đồ"><img src="http://x.vn/a.png">'})
    service.schedule(ME, post["id"], "2026-11-04 10:05", None, None)
    clock["now"] += 300
    assert worker.dispatch_due() == 1
    sent = service.get_post("u1", post["id"])
    assert sent["state"] == "sent" and sent["wp_status"] == "publish" and sent["ext_id"] == "a1"
    assert sent["wp_url"] == "https://zalo.me/article/a1"
    article = fake.created[0]
    assert article["status"] == "show" and article["author"] == "Duc Duong SCI" and article["description"] == "Giảm 10% phí hiệu chuẩn"
    assert article["cover"]["photo_url"].startswith("https://owui.example/api/v1/cqf/lich/public/" + post["id"] + "/")
    images = [b for b in article["body"] if b["type"] == "image"]
    assert len(images) == 1 and images[0]["url"].startswith("https://owui.example/") and images[0]["caption"] == "Sơ đồ"


def test_hidden_article_for_draft_mode(zalo):
    fake, clock, site = zalo
    post = zalo_post(site, mode="draft")
    service.schedule(ME, post["id"], "2026-11-04 10:05", None, None)
    clock["now"] += 300
    worker.dispatch_due()
    sent = service.get_post("u1", post["id"])
    assert fake.created[0]["status"] == "hide" and sent["wp_status"] == "draft" and sent["wp_url"] is None


def test_slow_zalo_is_asked_again_without_a_second_article(zalo):
    fake, clock, site = zalo
    fake.pending = 1
    post = zalo_post(site)
    service.schedule(ME, post["id"], "2026-11-04 10:05", None, None)
    clock["now"] += 300
    worker.dispatch_due()
    waiting = service.get_post("u1", post["id"])
    assert waiting["state"] == "sending" and "đang xử lý" in waiting["error"]
    clock["now"] += 60
    worker.dispatch_due()
    assert service.get_post("u1", post["id"])["state"] == "sent" and len(fake.created) == 1


def test_processing_answer_is_waited_for_and_retry_reuses_the_token(zalo, monkeypatch):
    fake, clock, site = zalo
    still = WpError("Zalo trả lỗi -214: Media is being processed")
    still.code = zalo_oa.PROCESSING
    calls = {"n": 0}
    real_verify = fake.verify

    def slow_verify(token):
        calls["n"] += 1
        if calls["n"] == 1:
            raise WpError("Không gọi được Zalo (/article/verify): timeout")  # a network hiccup after create
        return real_verify(token)

    monkeypatch.setattr(fake, "verify", slow_verify)
    post = zalo_post(site)
    service.schedule(ME, post["id"], "2026-11-04 10:05", None, None)
    clock["now"] += 300
    worker.dispatch_due()
    clock["now"] += 60
    worker.dispatch_due()
    assert service.get_post("u1", post["id"])["state"] == "sent" and len(fake.created) == 1


def test_minus_214_means_still_processing():
    answers = [{"error": -214, "message": "Media is being processed"}, {"error": 0, "data": {"id": "abc"}}]

    class Resp:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            import json as _json
            return _json.dumps(self.body).encode()

    client = zalo_oa.Client("999", token_fn=lambda force: "t", opener=lambda req, timeout: Resp(answers.pop(0)))
    assert client.verify("tok", tries=3, wait=0) == "abc"


def test_failed_post_keeps_the_zalo_token_when_rescheduled(zalo):
    fake, clock, site = zalo
    post = zalo_post(site)
    with db.tx() as conn:
        conn.execute("UPDATE posts SET state='failed', zalo_token='tok7', error='x' WHERE id=?", (post["id"],))
    service.schedule(ME, post["id"], "2026-11-04 10:05", None, None)
    assert db.one("SELECT zalo_token FROM posts WHERE id=?", (post["id"],))[0] == "tok7"


def test_broken_token_fails_at_once(zalo):
    fake, clock, site = zalo
    fake.fail = WpError("Token Zalo OA không dùng được (Zalo -216)", permanent=True)
    post = zalo_post(site)
    service.schedule(ME, post["id"], "2026-11-04 10:05", None, None)
    clock["now"] += 300
    worker.dispatch_due()
    assert service.get_post("u1", post["id"])["state"] == "failed"


def test_public_image_links_are_signed_and_expire(zalo):
    _, clock, site = zalo
    post = zalo_post(site)
    row = db.one("SELECT * FROM posts WHERE id=?", (post["id"],))
    link = service.public_link(post["id"], row["cover_file"])
    query = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    expires, signature = int(query["e"][0]), query["s"][0]
    assert service.public_file(post["id"], row["cover_file"], expires, signature) is not None
    assert service.public_file(post["id"], row["cover_file"], expires, "0" * 32) is None
    assert service.public_file(post["id"], "../secret.key", expires, signature) is None
    other = zalo_post(site)
    assert service.public_file(other["id"], row["cover_file"], expires, service._sign(other["id"], row["cover_file"], expires)) is None
    clock["now"] = expires + 1
    assert service.public_file(post["id"], row["cover_file"], expires, signature) is None


def test_big_images_are_shrunk_under_one_megabyte():
    from PIL import Image

    noise = Image.effect_noise((1800, 1800), 90).convert("RGB")
    raw = io.BytesIO()
    noise.save(raw, "PNG")
    assert raw.tell() > zalo_oa.MAX_IMAGE
    data, extension = zalo_oa.shrink_image(raw.getvalue())
    assert extension == ".jpg" and len(data) <= zalo_oa.MAX_IMAGE
    assert zalo_oa.shrink_image(PNG) == (PNG, "")
