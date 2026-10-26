"""API /api/v1/cqf cua chatbot website trong Open WebUI.

Cong khai (khung chat tren website khach, kiem Origin trong allowed_origins):
    GET  /webchat/widget.js          ma nhung; chatbot tat -> file rong
    POST /webchat/chat               {"vid", "text", "page"} -> {"reply"}
    POST /webchat/stream             cung dau vao, tra su kien SSE (status, delta, replace, done)
Quan tri (dang nhap Open WebUI, vai tro admin; dung get_admin_user cua Open WebUI):
    GET/POST /settings               cai dat (bat/tat, thong tin shop, khung chat, LLM, so lan tra toi thieu...)
    GET /kb, GET /kb/note, POST /kb/note, POST /kb/toggle, DELETE /kb/note, POST /kb/upload, GET /kb/search
    GET /inbox/index, GET /inbox/conv, POST /inbox/action, GET /status
    POST /test/stream                trang "Thu chatbot": nhu /webchat/stream + su kien trace, tin luu rieng (khong vao
                                     Hop thu), chay ca khi chatbot dang tat
    GET /test/sessions, GET /test/session, DELETE /test/session   lich su thu (tren server, theo quan tri vien)
"""
import json, tempfile, time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from open_webui.utils.auth import get_admin_user

from . import kb, store
from .engine import Engine
from .inbox import get_inbox
from .knowledge import Knowledge
from .testlog import TestLog

router = APIRouter()
STATIC = Path(__file__).parent / "static"
VID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
RATE_VID = (20, 300)  # toi da 20 tin / 5 phut / khach
RATE_IP = (60, 300)
_hits = defaultdict(deque)
_parts = {}


def parts():
    """Kien thuc, hop thu, engine: tao 1 lan khi co request dau tien (luc import Open WebUI chua san DATA_DIR)."""
    if not _parts:
        home = store.root()
        k = Knowledge(home)
        box = get_inbox(home, {})
        test_box = get_inbox(home / "test", {})  # tin thu cua quan tri vien: khong lan vao Hop thu
        _parts.update(home=home, k=k, inbox=box, engine=Engine(k, box), test_engine=Engine(k, test_box, trace=True),
                      test_log=TestLog(home))
    return _parts


def _rate_ok(key, rate):
    now, q = time.time(), _hits[key]
    while q and q[0] < now - rate[1]:
        q.popleft()
    if len(q) >= rate[0]:
        return False
    q.append(now)
    if len(_hits) > 20000:
        _hits.clear()
    return True


def _ip(request: Request):
    fwd = request.headers.get("x-forwarded-for", "")
    host = request.client.host if request.client else ""
    return fwd.split(",")[-1].strip() if fwd and host in ("127.0.0.1", "::1") else host


def _origin_ok(request: Request, s):
    origin = (request.headers.get("origin") or "").rstrip("/")
    own = f"{request.url.scheme}://{request.headers.get('host', '')}"
    forwarded = f"{request.headers.get('x-forwarded-proto', 'https')}://{request.headers.get('host', '')}"
    return bool(origin) and (origin in s["allowed_origins"] or origin in (own, forwarded))  # trang Chatbot thu ngay


def _err(e: Exception):
    raise HTTPException(400, detail=str(e))


# ---------------------------------------------------------------- khung chat cong khai

@router.get("/webchat/widget.js")
async def widget(request: Request):
    s = store.load(parts()["home"])
    if not s["enabled"]:
        return Response("/* chatbot dang tat */", media_type="application/javascript", headers={"Cache-Control": "no-cache"})
    conf = {**s["widget"], "shop": s["business"].get("ten") or "", "api": "/api/v1/cqf/webchat"}
    js = (STATIC / "widget.js").read_text(encoding="utf-8").replace("__WEBCHAT_CONFIG__", json.dumps(conf, ensure_ascii=False))
    return Response(js, media_type="application/javascript", headers={"Cache-Control": "public, max-age=120"})


async def _chat_input(request: Request):
    """Kiem tra chung cho /chat va /stream. Tra (settings, conv, text, page) hoac JSONResponse loi."""
    s = store.load(parts()["home"])
    headers = {"Cache-Control": "no-store"}
    if not _origin_ok(request, s):
        return JSONResponse({"ok": False, "error": "origin"}, 403, headers)
    if not s["enabled"]:
        return JSONResponse({"ok": False, "error": "off"}, 503, headers)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "error": "json"}, 400, headers)
    vid, text = str(body.get("vid", "")), str(body.get("text", "")).strip()
    if not (8 <= len(vid) <= 64 and set(vid) <= VID_OK) or not text:
        return JSONResponse({"ok": False, "error": "vid/text"}, 400, headers)
    if len(text) > 1000:
        return JSONResponse({"ok": False, "error": "qua dai"}, 413, headers)
    if not _rate_ok(vid, RATE_VID) or not _rate_ok("ip:" + _ip(request), RATE_IP):
        return JSONResponse({"ok": False, "error": "rate"}, 429, headers)
    return s, f"web:{vid}", text, str(body.get("page") or "")[:300] or None


@router.post("/webchat/chat")
async def chat(request: Request):
    got = await _chat_input(request)
    if isinstance(got, Response):
        return got
    reply = await parts()["engine"].answer(*got)
    return JSONResponse({"ok": True, "reply": reply}, 200, {"Cache-Control": "no-store"})


@router.post("/webchat/stream")
async def chat_stream(request: Request):
    """Su kien SSE: status (buoc tra kien thuc...), delta (doan chu da qua kiem so lieu), replace, done."""
    got = await _chat_input(request)
    if isinstance(got, Response):
        return got

    async def events():
        async for ev in parts()["engine"].stream(*got):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- thu chatbot (quan tri vien)

@router.post("/test/stream")
async def test_stream(request: Request, user=Depends(get_admin_user)):
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, detail="JSON không hợp lệ")
    sid, text = str(body.get("sid", "")), str(body.get("text", "")).strip()
    if not (8 <= len(sid) <= 64 and set(sid) <= VID_OK) or not text:
        raise HTTPException(400, detail="Thiếu nội dung")
    if len(text) > 1000:
        raise HTTPException(413, detail="Tin nhắn quá dài (tối đa 1000 ký tự)")
    s = store.load(parts()["home"])

    async def events():
        answer, trace = "", {"tools": []}
        try:
            async for ev in parts()["test_engine"].stream(s, f"test:{user.id}:{sid}", text):
                kind = ev["type"]
                if kind == "delta":
                    answer += ev["text"]
                elif kind == "replace":
                    answer = ev["text"]
                elif kind == "trace":
                    step = ev["step"]
                    if step == "auto":
                        trace["auto"] = {"queries": ev["queries"], "hits": ev["hits"]}
                    elif step == "tool":
                        trace["tools"].append({k: ev[k] for k in ("name", "args", "result")})
                    elif step == "blocked":
                        trace["blocked"] = {"numbers": ev["numbers"], "draft": ev["draft"]}
                    elif step == "empty":
                        trace["empty"] = ev["rounds"]
                    elif step == "error":
                        trace["error"] = ev["text"]
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:  # luu ca khi trinh duyet dong giua chung (tra loi den dau luu den do)
            parts()["test_log"].add(user.id, sid, text, answer or "_(bị ngắt)_", trace)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/test/sessions")
async def test_sessions(user=Depends(get_admin_user)):
    return {"ok": True, "sessions": parts()["test_log"].sessions(user.id)}


@router.get("/test/session")
async def test_session(sid: str, user=Depends(get_admin_user)):
    try:
        data = parts()["test_log"].get(user.id, sid)
    except ValueError:
        raise HTTPException(400, detail="sid")
    if not data:
        raise HTTPException(404, detail="Không có cuộc thử này")
    return {"ok": True, "session": data}


@router.delete("/test/session")
async def test_session_delete(sid: str, user=Depends(get_admin_user)):
    try:
        parts()["test_log"].delete(user.id, sid)
    except ValueError:
        raise HTTPException(400, detail="sid")
    return {"ok": True}


# ---------------------------------------------------------------- cai dat

@router.get("/settings")
async def get_settings(request: Request, user=Depends(get_admin_user)):
    s = store.load(parts()["home"])
    base = f"{request.headers.get('x-forwarded-proto', request.url.scheme)}://{request.headers.get('host', '')}"
    return {"ok": True, "settings": store.public(s), "embed": f'<script src="{base}/api/v1/cqf/webchat/widget.js" defer></script>'}


@router.post("/settings")
async def post_settings(request: Request, user=Depends(get_admin_user)):
    patch = await request.json()
    allowed = {k: patch[k] for k in ("enabled", "business", "widget", "allowed_origins", "thu_thap_khach", "fallback_text",
                                     "min_searches", "max_passages", "max_tool_rounds", "llm", "tu_van") if k in patch}
    try:
        s = store.save(allowed, parts()["home"])
    except (ValueError, TypeError) as e:
        _err(e)
    return {"ok": True, "settings": store.public(s)}


@router.post("/settings/test")
async def test_llm(user=Depends(get_admin_user)):
    """Thu goi LLM bang cai dat hien tai (nut "Thu ket noi")."""
    s = store.load(parts()["home"])
    try:
        msg = await parts()["engine"]._llm(s["llm"], [{"role": "user", "content": "Trả lời đúng 1 từ: OK"}])
        return {"ok": True, "reply": (msg.get("content") or "")[:100]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


# ---------------------------------------------------------------- kien thuc

@router.get("/kb")
async def kb_list(user=Depends(get_admin_user)):
    return {"ok": True, "notes": parts()["k"].list()}


@router.get("/kb/note")
async def kb_get(name: str, user=Depends(get_admin_user)):
    try:
        return {"ok": True, "note": parts()["k"].get(name)}
    except kb.KbError as e:
        _err(e)


@router.post("/kb/note")
async def kb_save(request: Request, user=Depends(get_admin_user)):
    b = await request.json()
    known = " ".join(str(v) for v in store.load(parts()["home"])["business"].values())
    try:
        return {"ok": True, "note": parts()["k"].save(b.get("name") or None, b.get("title"), b.get("body"), b.get("enabled"), known)}
    except kb.KbError as e:
        _err(e)


@router.post("/kb/toggle")
async def kb_toggle(request: Request, user=Depends(get_admin_user)):
    b = await request.json()
    try:
        parts()["k"].set_enabled(str(b.get("name", "")), bool(b.get("enabled")))
    except kb.KbError as e:
        _err(e)
    return {"ok": True}


@router.delete("/kb/note")
async def kb_delete(name: str, user=Depends(get_admin_user)):
    try:
        parts()["k"].delete(name)
    except kb.KbError as e:
        _err(e)
    return {"ok": True}


@router.post("/kb/upload")
async def kb_upload(files: list[UploadFile] = File(...), user=Depends(get_admin_user)):
    done, errors = [], []
    for f in files[:20]:
        name = Path(f.filename or "tai-lieu").name
        with tempfile.NamedTemporaryFile(suffix=Path(name).suffix) as tmp:
            size = 0
            while chunk := await f.read(1024 * 1024):
                size += len(chunk)
                if size > 15 * 1024 * 1024:
                    errors.append(f"{name}: quá 15 MB")
                    break
                tmp.write(chunk)
            else:
                tmp.flush()
                try:
                    done.append({"file": name, **parts()["k"].upload(Path(tmp.name), name)})
                except kb.KbError as e:
                    errors.append(str(e))
    return {"ok": not errors, "done": done, "errors": errors}


@router.get("/kb/search")
async def kb_search(q: str, user=Depends(get_admin_user)):
    """Thu tim nhu bot: tra cac cau tra ma bot se dung (toi thieu N lan) va doan tim duoc."""
    from .engine import queries
    s = store.load(parts()["home"])
    qs = queries(q, "", int(s["min_searches"]))
    seen, hits = set(), []
    for one in qs:
        for h in parts()["k"].search(one, int(s["max_passages"])):
            if (h["source"], h["chunk"]) not in seen:
                seen.add((h["source"], h["chunk"]))
                hits.append(h)
    hits.sort(key=lambda h: -h["score"])
    return {"ok": True, "queries": qs, "hits": hits[:int(s["max_passages"])]}


# ---------------------------------------------------------------- hop thu

@router.get("/inbox/index")
async def inbox_index(user=Depends(get_admin_user)):
    return {"ok": True, "me": user.name, **parts()["inbox"].index()}


@router.get("/inbox/conv")
async def inbox_conv(c: str, user=Depends(get_admin_user)):
    data = parts()["inbox"].conversation(c)
    if data is None:
        raise HTTPException(404, detail="not_found")
    return {"ok": True, **data}


@router.post("/inbox/action")
async def inbox_action(request: Request, user=Depends(get_admin_user)):
    b = await request.json()
    ok = parts()["inbox"].action(str(b.get("conv", "")), str(b.get("action", "")), user.name)
    if not ok:
        raise HTTPException(400, detail="action")
    return {"ok": True}


@router.post("/inbox/profile")
async def inbox_profile(request: Request, user=Depends(get_admin_user)):
    """Chu shop sua ten / SDT / Zalo / nhu cau cua khach tren Hop thu."""
    b = await request.json()
    if not parts()["inbox"].update_profile(str(b.get("conv", "")), b.get("profile") or {}, user.name):
        raise HTTPException(404, detail="not_found")
    return {"ok": True}


@router.get("/status")
async def status(user=Depends(get_admin_user)):
    p = parts()
    s = store.load(p["home"])
    items = p["inbox"].index()["items"]
    return {"ok": True, "enabled": s["enabled"], "todo": sum(1 for it in items if it["status"] == "can_xu_ly"),
            "notes": sum(1 for n in p["k"].list() if n["enabled"]), "llm_ready": bool(s["llm"]["base_url"] and s["llm"]["model"])}
