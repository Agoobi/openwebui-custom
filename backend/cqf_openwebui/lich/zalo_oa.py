"""Lich dang: Zalo OA articles (openapi.zalo.me v2.0 article/*).

Tokens come from the same store as the chatbot's Zalo channel (<cqf>/zalo/tokens.json, file lock while refreshing):
a Zalo refresh token works once, so nobody may keep a copy. App ID / App Secret come from the chatbot settings.

An article is plain text blocks and image blocks; Zalo drops every HTML tag and turns line breaks into spaces, so
each paragraph, heading and list item is its own text block. Images must be public https URLs <= 1 MB: Zalo downloads
them while it processes the article. create answers with a token; verify turns it into the article id once Zalo is
done, so the token is kept on the post: a retry asks again with the same token instead of making a second article.
"""

import html
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .wordpress import WpError

API = "https://openapi.zalo.me/v2.0"
LIMITS = {"title": 150, "author": 50, "description": 300}
MAX_IMAGE = 1024 * 1024
TOKEN_ERRORS = {-216, -124}
PERMANENT_ERRORS = {
    -230: "OA chưa cấp quyền quản lý bài viết cho app Zalo: chủ OA kết nối lại và bật quyền bài viết.",
    -201: "Zalo từ chối bài (tiêu đề, mô tả quá dài, hoặc không tải được ảnh bìa).",
    -216: "Token Zalo OA không dùng được: nạp lại token ở trang Chatbot > Kênh Zalo OA.",
    -124: "Token Zalo OA hết hạn và không làm mới được: nạp lại token ở trang Chatbot > Kênh Zalo OA.",
}
MANAGE_URL = "https://oa.zalo.me/manage/article"
UA = "LichDang/1.0 (+openwebui-custom; Zalo OA)"


def _cqf_home() -> Path:
    from ..store import root

    return root()


def _app(oa_id: str) -> dict:
    """The chatbot's Zalo settings (app id + secret) with the OA to act for."""
    from .. import store

    z = dict(store.load().get("zalo") or {})
    z["oa_id"] = str(oa_id)
    return z


def connected_oas() -> list[dict]:
    """OAs that have a token in the shared store."""
    path = _cqf_home() / "zalo" / "tokens.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [{"oa_id": oa_id, "name": entry.get("name") or f"OA {oa_id}"}
            for oa_id, entry in (data.get("oas") or {}).items() if entry.get("refresh_token")]


class Client:
    def __init__(self, oa_id: str, token_fn=None, opener=None):
        self.oa_id = str(oa_id)
        self._token_fn = token_fn or self._shared_token
        self._open = opener or urllib.request.urlopen

    def _shared_token(self, force: bool) -> str:
        from .. import zalo

        try:
            return zalo.access_token(_cqf_home(), _app(self.oa_id), force=force)
        except zalo.ZaloError as error:
            raise WpError(str(error), permanent=True) from error

    def call(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        force = False
        for attempt in (0, 1):
            token = self._token_fn(force)
            url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
            data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
            req = urllib.request.Request(url, data=data, method=method, headers={
                "access_token": token, "Content-Type": "application/json", "User-Agent": UA})
            try:
                with self._open(req, timeout=60) as r:
                    res = json.loads(r.read() or b"{}")
            except urllib.error.HTTPError as error:
                raise WpError(f"Zalo trả lỗi HTTP {error.code} ({path}).") from error
            except (urllib.error.URLError, OSError, ValueError) as error:
                raise WpError(f"Không gọi được Zalo ({path}): {error}") from error
            code = res.get("error", 0)
            if code in TOKEN_ERRORS and attempt == 0:
                force = True  # the token was refused: refresh once and try again
                continue
            if code:
                message = PERMANENT_ERRORS.get(code)
                if message:
                    raise WpError(f"{message} (Zalo {code})", permanent=True)
                raise WpError(f"Zalo trả lỗi {code}: {res.get('message', '')}", permanent=code not in (-224, -32, -200))
            return res.get("data") or {}
        raise WpError("Zalo từ chối token OA.", permanent=True)

    def check(self) -> dict:
        self.call("GET", "/article/getslice", params={"offset": 0, "limit": 1, "type": "normal"})
        return {"ok": True}

    def create(self, article: dict) -> str:
        data = self.call("POST", "/article/create", body=article)
        if not data.get("token"):
            raise WpError(f"Zalo không trả mã chờ khi tạo bài: {data}")
        return str(data["token"])

    def verify(self, token: str, tries: int = 6, wait: float = 2.0) -> str | None:
        """The article id once Zalo has processed it; None while it is still working."""
        for attempt in range(tries):
            try:
                data = self.call("POST", "/article/verify", body={"token": token})
            except WpError as error:
                if "failed" in error.message.lower() or "-200" in error.message:
                    raise WpError("Zalo xử lý bài thất bại, thường do ảnh quá 1 MB hoặc Zalo không tải được ảnh: "
                                  + error.message, permanent=True) from error
                raise
            if data.get("id"):
                return str(data["id"])
            if attempt < tries - 1:
                time.sleep(wait)
        return None

    def detail(self, article_id: str) -> dict:
        return self.call("GET", "/article/getdetail", params={"id": article_id})


# ------------------------------------------------------------------ html -> Zalo blocks

class _Blocks(HTMLParser):
    BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "tr", "figcaption", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self.buf: list[str] = []
        self.stack: list[str] = []
        self.href: str | None = None
        self.lists: list[list] = []

    def _flush(self):
        text = " ".join("".join(self.buf).split())
        self.buf = []
        if not text:
            return
        kind = self.stack[-1] if self.stack else "p"
        if kind in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = text.upper()
        elif kind == "li":
            mark = "•"
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                mark = f"{self.lists[-1][1]}."
            text = f"{mark} {text}"
        elif kind == "blockquote":
            text = f"“{text}”"
        # Zalo decodes entities, so < > & are escaped to stay text.
        self.items.append({"type": "text", "content": html.escape(text, quote=False)})

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("ul", "ol"):
            self._flush()
            self.lists.append([tag, 0])
        elif tag in self.BLOCK:
            self._flush()
            self.stack.append(tag)
        elif tag == "br":
            self._flush()
        elif tag == "img" and a.get("src"):
            self._flush()
            self.items.append({"type": "image", "url": a["src"], "caption": a.get("alt", "")})
        elif tag == "a":
            self.href = a.get("href")
        elif tag in ("td", "th"):
            self.buf.append(" | " if self.buf else "")

    def handle_endtag(self, tag):
        if tag in ("ul", "ol"):
            self._flush()
            if self.lists:
                self.lists.pop()
        elif tag in self.BLOCK:
            self._flush()
            if tag in self.stack:
                self.stack.remove(tag)
        elif tag == "a":
            self.href = None

    def handle_data(self, data):
        if self.href and data.strip() and data.strip() != self.href:
            self.buf.append(f"{data} ({self.href})")
        else:
            self.buf.append(data)

    def close(self):
        super().close()
        self._flush()


def html_to_blocks(text: str) -> list[dict]:
    parser = _Blocks()
    parser.feed(text or "")
    parser.close()
    return parser.items


def plain_length(text: str) -> int:
    return len(" ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split()))


def shrink_image(data: bytes) -> tuple[bytes, str]:
    """An image Zalo accepts: <= 1 MB. Bigger ones become a JPEG, scaled down until they fit."""
    if len(data) <= MAX_IMAGE:
        return data, ""
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    width, height = img.size
    for scale in (1.0, 0.85, 0.7, 0.55, 0.42, 0.32):
        size = (max(1, int(width * scale)), max(1, int(height * scale)))
        resized = img if scale == 1.0 else img.resize(size, Image.LANCZOS)
        for quality in (86, 78, 70):
            out = io.BytesIO()
            resized.save(out, "JPEG", quality=quality, optimize=True)
            if out.tell() <= MAX_IMAGE:
                return out.getvalue(), ".jpg"
    raise WpError("Ảnh quá lớn, thu nhỏ không xuống được 1 MB cho Zalo.", permanent=True)
