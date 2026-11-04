"""WordPress REST API with an application password (Basic auth). Works with any self-hosted WordPress 5.6+."""

import html
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import config


class WpError(Exception):
    """A failed call. permanent=True means retrying will not help (wrong password, missing rights...)."""

    def __init__(self, message: str, permanent: bool = False, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.permanent = permanent
        self.status = status


def normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parts = urlsplit(url)
    if not parts.netloc:
        raise WpError("Địa chỉ site không hợp lệ.", permanent=True)
    return url


def _firewall_message(host: str) -> str:
    ip = f" ({config.SERVER_PUBLIC_IP})" if config.SERVER_PUBLIC_IP else ""
    return (
        f"Tường lửa của hosting {host} chặn máy chủ Lịch đăng{ip}: yêu cầu bị trả 503/thử thách trước khi tới "
        f"WordPress. Nhờ hosting (hoặc vào bảng điều khiển hosting) cho IP{ip} vào danh sách cho phép."
    )


class WordPress:
    def __init__(self, url: str, username: str, app_password: str):
        self.url = normalize_url(url)
        self.host = urlsplit(self.url).netloc
        self.api = self.url + "/wp-json/wp/v2"
        self._client = httpx.Client(
            auth=(username, app_password.replace(" ", "")),
            timeout=config.HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _request(self, method: str, path: str, **kwargs):
        target = path if path.startswith("http") else self.api + path
        try:
            response = self._client.request(method, target, **kwargs)
        except httpx.TimeoutException as error:
            raise WpError(f"{self.host} không trả lời trong {config.HTTP_TIMEOUT_SECONDS} giây.") from error
        except httpx.HTTPError as error:
            raise WpError(f"Không kết nối được tới {self.host}: {error}") from error

        body = None
        if "json" in response.headers.get("content-type", ""):
            try:
                body = response.json()
            except ValueError:
                body = None

        if response.status_code < 400 and body is not None:
            return body

        challenged = "osh-mitigated" in response.headers or "cf-mitigated" in response.headers
        if response.status_code in (403, 429, 503) and (challenged or body is None):
            raise WpError(_firewall_message(self.host), status=response.status_code)

        message = ""
        code = ""
        if isinstance(body, dict):
            message = html.unescape(str(body.get("message", "")))
            code = str(body.get("code", ""))

        if response.status_code == 401:
            if code == "rest_not_logged_in":
                raise WpError(
                    "WordPress không nhận đăng nhập: application password sai (hoặc đã bị thu hồi), hoặc máy chủ web "
                    "bỏ header Authorization. Kiểm tra lại mật khẩu; nếu chắc chắn đúng thì thêm vào .htaccess: "
                    "SetEnvIf Authorization \"(.*)\" HTTP_AUTHORIZATION=$1",
                    permanent=True,
                    status=401,
                )
            raise WpError(
                "Sai tên đăng nhập hoặc application password (" + (message or code or "401") + ").",
                permanent=True,
                status=401,
            )
        if response.status_code == 403:
            raise WpError("Tài khoản WordPress không đủ quyền: " + (message or code), permanent=True, status=403)
        if response.status_code == 404 and code in ("", "rest_no_route"):
            raise WpError(
                f"Không thấy REST API ở {self.url}/wp-json (site tắt REST API hoặc sai địa chỉ).",
                permanent=True,
                status=404,
            )
        if response.status_code >= 500:
            raise WpError(f"{self.host} lỗi {response.status_code}: {message or 'máy chủ bận'}", status=response.status_code)
        if response.status_code < 400:
            raise WpError(f"{self.host} trả về nội dung không phải JSON (có thể là trang chặn của hosting).")
        raise WpError(f"WordPress từ chối ({response.status_code}): {message or code}", permanent=True, status=response.status_code)

    # Account and site

    def me(self) -> dict:
        return self._request("GET", "/users/me", params={"context": "edit"})

    def site_timezone(self) -> str | None:
        try:
            return self._request("GET", "/settings").get("timezone") or None
        except WpError:
            return None

    def check(self) -> dict:
        """What the scheduler needs: publish, upload, and whether raw HTML (style tags) survives."""
        me = self.me()
        caps = me.get("capabilities") or {}
        missing = [name for name in ("publish_posts", "upload_files", "edit_posts") if not caps.get(name)]
        if missing:
            raise WpError(
                "Tài khoản " + str(me.get("username") or me.get("name")) + " thiếu quyền: " + ", ".join(missing)
                + ". Dùng tài khoản Biên tập viên hoặc Quản trị.",
                permanent=True,
            )
        return {
            "user": me.get("name") or me.get("username"),
            "roles": me.get("roles") or [],
            "unfiltered_html": bool(caps.get("unfiltered_html")),
            "timezone": self.site_timezone(),
        }

    # Posts

    def find_by_slug(self, slug: str) -> dict | None:
        found = self._request(
            "GET",
            "/posts",
            params={"slug": slug, "status": "publish,future,draft,pending,private", "context": "edit", "per_page": 5},
        )
        return found[0] if found else None

    def get_post(self, post_id: int) -> dict | None:
        try:
            return self._request("GET", f"/posts/{post_id}", params={"context": "edit"})
        except WpError as error:
            if error.status in (404, 410):
                return None
            raise

    def save_post(self, post_id: int | None, payload: dict) -> dict:
        path = f"/posts/{post_id}" if post_id else "/posts"
        return self._request("POST", path, json=payload)

    def term_ids(self, taxonomy: str, names: list[str]) -> list[int]:
        ids: list[int] = []
        for raw in names:
            name = raw.strip()
            if not name:
                continue
            found = self._request("GET", f"/{taxonomy}", params={"search": name, "per_page": 100, "context": "view"})
            match = next((t for t in found if html.unescape(t.get("name", "")).casefold() == name.casefold()), None)
            if match is None:
                try:
                    match = self._request("POST", f"/{taxonomy}", json={"name": name})
                except WpError as error:
                    # Another request created it in between: WordPress answers term_exists with the id.
                    if "term_exists" in error.message:
                        found = self._request("GET", f"/{taxonomy}", params={"search": name, "per_page": 100})
                        match = next((t for t in found if html.unescape(t.get("name", "")).casefold() == name.casefold()), None)
                    if match is None:
                        raise
            ids.append(int(match["id"]))
        return ids

    def upload_media(self, path: Path, filename: str, alt: str) -> int:
        mime = mimetypes.guess_type(filename)[0] or "image/jpeg"
        media = self._request(
            "POST",
            "/media",
            content=path.read_bytes(),
            headers={"Content-Type": mime, "Content-Disposition": f'attachment; filename="{filename}"'},
        )
        if alt:
            self._request("POST", f"/media/{media['id']}", json={"alt_text": alt})
        return int(media["id"])
