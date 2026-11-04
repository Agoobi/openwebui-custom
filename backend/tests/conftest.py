"""Lich dang tests: a throwaway data folder, a fixed clock and a fake WordPress.

Run from backend/: python -m pytest -q tests  (needs fastapi, httpx, cryptography, pytest)
"""

import os
import sys
import tempfile
from pathlib import Path

HOME = tempfile.mkdtemp()
os.environ.update(LICH_HOME=HOME, OWUI_DB=os.path.join(HOME, "no-webui.db"), LICH_SERVER_IP="203.0.113.7")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from cqf_openwebui.lich import config, db, service, timeutil, worker  # noqa: E402
from cqf_openwebui.lich.service import Actor, Refused  # noqa: E402
from cqf_openwebui.lich.wordpress import WpError  # noqa: E402

ME = Actor("u1", "Người duyệt")
AGENT = Actor("u1", "Agent Content", is_agent=True)


class FakeWP:
    url = "https://example.test"

    def __init__(self):
        self.posts: dict[int, dict] = {}
        self.saves = 0
        self.fail_with: WpError | None = None
        self.fail_after_save = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get_post(self, post_id):
        return self.posts.get(post_id)

    def find_by_slug(self, slug):
        return next((p for p in self.posts.values() if p["slug"] == slug), None)

    def upload_media(self, path, filename, alt):
        return 77

    categories_on_site = ("Tin tức", "Thử lịch đăng")

    def term_ids(self, taxonomy, names, create=True):
        if not create:
            for name in names:
                if name not in self.categories_on_site:
                    raise WpError(f'Chuyên mục "{name}" không có trên example.test. Chọn chuyên mục có sẵn.', permanent=True)
        return [len(n) for n in names]

    def upload_media_url(self, path, filename, alt):
        self.uploads = getattr(self, "uploads", []) + [filename]
        return 90 + len(self.uploads), f"{self.url}/wp-content/uploads/{filename}"

    def save_post(self, post_id, payload):
        if self.fail_with:
            raise self.fail_with
        self.saves += 1
        post_id = post_id or 1000 + len(self.posts)
        self.posts[post_id] = {"id": post_id, "slug": payload["slug"], "title": {"raw": payload["title"]},
                               "status": payload["status"], "link": f"{self.url}/{payload['slug']}/",
                               "content": payload["content"]}
        if self.fail_after_save:
            self.fail_after_save = False
            raise WpError("example.test không trả lời trong 40 giây.")
        return self.posts[post_id]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    with db.tx() as conn:
        for table in ("posts", "history", "settings", "sites", "calendars"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute(
            "INSERT INTO sites (id, user_id, name, url, username, secret, created_at, updated_at) "
            "VALUES ('s1','u1','Example','https://example.test','admin',?,0,0)",
            (service.seal("abcd efgh"),),
        )
    fake = FakeWP()
    monkeypatch.setattr(service, "client_for", lambda row: fake)
    clock = {"now": timeutil.parse_moment("2026-11-04 10:00", "Asia/Ho_Chi_Minh")}
    monkeypatch.setattr(timeutil, "now", lambda: clock["now"])
    return fake, clock


