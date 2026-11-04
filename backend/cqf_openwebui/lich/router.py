"""API /api/v1/cqf/lich of Lich dang (scheduled WordPress posts), mounted by cqf_openwebui.router.

People: signed in to Open WebUI (any approved user; each user has their own sites, posts and settings).
Agent (Hermes on the same machine): header X-Lich-Agent-Token from <DATA_DIR>/cqf/lich/agent.json, acting for the
user named there. The agent cannot touch sites or settings (rule "agent").

    GET  /me                          settings, sites, rules, worker state
    GET  /timezones
    PUT  /settings                    timezone, default_mode, default_site_id, slots
    GET/POST /sites, PATCH/DELETE /sites/{id}, POST /sites/{id}/check
    GET  /posts?start&end&state       POST /posts
    GET/PATCH /posts/{id}             POST /posts/{id}/schedule|mode|unschedule|retry|archive
    GET/POST/DELETE /posts/{id}/cover  POST /posts/{id}/media, GET /media/{post}/{name}  (images inside the post)
    GET  /sites/{id}/categories        categories the site has; a post may only use these
    GET  /slots/next?count
    GET/POST /agent                   who the agent works for; POST makes it work for the caller (admin)
"""

import hmac
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config, service, timeutil, worker
from .service import Actor, Refused

router = APIRouter()


def _token_of(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get("token")


async def current_actor(request: Request) -> Actor:
    agent_token = request.headers.get("x-lich-agent-token")
    if agent_token:
        agent = config.agent()
        if agent.get("user_id") and hmac.compare_digest(agent_token, agent["token"]):
            return Actor(agent["user_id"], agent.get("name") or "Agent", is_agent=True)
        raise Refused("Token của agent không đúng, hoặc chưa chọn agent làm việc cho ai.", 401)

    token = _token_of(request)
    if not token:
        raise Refused("Chưa đăng nhập Open WebUI.", 401)
    from open_webui.utils.auth import get_verified_user_by_token

    user = await get_verified_user_by_token(token, getattr(request.app.state, "redis", None))
    if user is None:
        raise Refused("Phiên đăng nhập Open WebUI đã hết, đăng nhập lại.", 401)
    return Actor(user.id, user.name or user.email or "Người dùng", role=user.role)


def _range(start: str | None, end: str | None) -> tuple[int | None, int | None]:
    if not start or not end:
        return None, None
    try:
        return timeutil.parse_moment(start, "UTC"), timeutil.parse_moment(end, "UTC")
    except ValueError as error:
        raise Refused(str(error)) from error


def _agent_public(actor: Actor) -> dict:
    agent = config.agent()
    return {
        "works_for_me": agent.get("user_id") == actor.user_id,
        "assigned": bool(agent.get("user_id")),
        "name": agent.get("name") or "Agent",
        "token_file": str(config.AGENT_FILE),
    }


# Overview


@router.get("/me")
def me(actor: Actor = Depends(current_actor)):
    status = dict(worker.status)
    return {
        "user": {"id": actor.user_id, "name": actor.name, "is_agent": actor.is_agent},
        "settings": service.get_settings(actor.user_id),
        "sites": service.list_sites(actor.user_id),
        "rules": config.RULES,
        "states": config.STATE_LABELS,
        "modes": config.MODE_LABELS,
        "min_lead_seconds": config.MIN_LEAD_SECONDS,
        "server_ip": config.SERVER_PUBLIC_IP,
        "agent": None if actor.is_agent else _agent_public(actor),
        "worker": {k: (timeutil.iso_utc(v) if k.endswith("_at") else v) for k, v in status.items()},
        "now": timeutil.iso_utc(timeutil.now()),
    }


@router.get("/timezones")
def timezones(_: Actor = Depends(current_actor)):
    return timeutil.zone_names()


@router.post("/agent")
def claim_agent(actor: Actor = Depends(current_actor)):
    """The agent from now on reads and schedules posts for the caller. Only an admin may move it."""
    if actor.is_agent or actor.role != "admin":
        raise Refused("Chỉ quản trị viên Open WebUI mới đổi được agent làm việc cho ai.", 403)
    agent = config.agent()
    agent["user_id"] = actor.user_id
    config.save_agent(agent)
    return _agent_public(actor)


# Settings and sites


class SettingsIn(BaseModel):
    timezone: str | None = None
    default_mode: str | None = None
    default_site_id: str | None = None
    slots: list[dict] | None = None


@router.put("/settings")
def put_settings(body: SettingsIn, actor: Actor = Depends(current_actor)):
    return service.save_settings(actor, body.model_dump(exclude_unset=True))


class SiteIn(BaseModel):
    name: str | None = None
    url: str | None = None
    username: str | None = None
    app_password: str | None = None


@router.get("/sites")
def get_sites(actor: Actor = Depends(current_actor)):
    return service.list_sites(actor.user_id)


@router.post("/sites")
def post_site(body: SiteIn, actor: Actor = Depends(current_actor)):
    return service.save_site(actor, None, body.model_dump())


@router.patch("/sites/{site_id}")
def patch_site(site_id: str, body: SiteIn, actor: Actor = Depends(current_actor)):
    return service.save_site(actor, site_id, body.model_dump())


@router.post("/sites/{site_id}/check")
def check_site(site_id: str, actor: Actor = Depends(current_actor)):
    return service.check_site(actor, site_id)


@router.get("/sites/{site_id}/categories")
def site_categories(site_id: str, actor: Actor = Depends(current_actor)):
    """Categories the site has (posts may only use these)."""
    return service.site_categories(actor, site_id)


@router.delete("/sites/{site_id}")
def delete_site(site_id: str, actor: Actor = Depends(current_actor)):
    service.delete_site(actor, site_id)
    return {"ok": True}


# Posts


@router.get("/posts")
def get_posts(start: str | None = None, end: str | None = None, state: str | None = None,
              actor: Actor = Depends(current_actor)):
    if state and state not in config.STATES:
        raise Refused("Trạng thái không hợp lệ.")
    begin, finish = _range(start, end)
    return service.list_posts(actor.user_id, begin, finish, state)


class PostIn(BaseModel):
    title: str | None = None
    html: str | None = None
    excerpt: str | None = None
    slug: str | None = None
    categories: list[str] | str | None = None
    tags: list[str] | str | None = None
    cover_alt: str | None = None
    site_id: str | None = None
    mode: str | None = None
    publish_at: Any = None
    timezone: str | None = None


@router.post("/posts")
def create_post(body: PostIn, actor: Actor = Depends(current_actor)):
    return service.create_post(actor, body.model_dump(exclude_unset=True))


@router.get("/posts/{post_id}")
def read_post(post_id: str, actor: Actor = Depends(current_actor)):
    return service.get_post(actor.user_id, post_id)


@router.patch("/posts/{post_id}")
def patch_post(post_id: str, body: PostIn, actor: Actor = Depends(current_actor)):
    return service.update_post(actor, post_id, body.model_dump(exclude_unset=True))


class ScheduleIn(BaseModel):
    publish_at: Any = None  # "2026-11-10 08:00" (in timezone), ISO with offset, epoch seconds, or "next"
    timezone: str | None = None
    mode: str | None = None


@router.post("/posts/{post_id}/schedule")
def schedule(post_id: str, body: ScheduleIn, actor: Actor = Depends(current_actor)):
    return service.schedule(actor, post_id, body.publish_at, body.timezone, body.mode)


class ModeIn(BaseModel):
    mode: str


@router.post("/posts/{post_id}/mode")
def set_mode(post_id: str, body: ModeIn, actor: Actor = Depends(current_actor)):
    return service.set_mode(actor, post_id, body.mode)


@router.post("/posts/{post_id}/unschedule")
def unschedule(post_id: str, actor: Actor = Depends(current_actor)):
    return service.unschedule(actor, post_id)


@router.post("/posts/{post_id}/retry")
def retry(post_id: str, actor: Actor = Depends(current_actor)):
    """A failed post goes out again two minutes from now."""
    return service.schedule(actor, post_id, timeutil.now() + config.MIN_LEAD_SECONDS, "UTC", None)


@router.post("/posts/{post_id}/archive")
def archive(post_id: str, actor: Actor = Depends(current_actor)):
    service.archive(actor, post_id)
    return {"ok": True}


@router.post("/posts/{post_id}/cover")
async def upload_cover(post_id: str, file: UploadFile = File(...), alt: str | None = Form(None),
                       actor: Actor = Depends(current_actor)):
    content = await file.read(config.MAX_COVER_BYTES + 1)
    return service.set_cover(actor, post_id, content, file.filename or "cover", alt)


@router.delete("/posts/{post_id}/cover")
def delete_cover(post_id: str, actor: Actor = Depends(current_actor)):
    return service.remove_cover(actor, post_id)


@router.get("/posts/{post_id}/cover")
def get_cover(post_id: str, actor: Actor = Depends(current_actor)):
    path = service.cover_path(actor.user_id, post_id)
    if not path or not path.exists():
        raise Refused("Bài chưa có ảnh bìa.", 404)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=300"})


@router.post("/posts/{post_id}/media")
async def upload_media(post_id: str, file: UploadFile = File(...), actor: Actor = Depends(current_actor)):
    """An image for inside the post: returns the url to put in the html (<img src=...>)."""
    content = await file.read(config.MAX_COVER_BYTES + 1)
    return service.add_media(actor, post_id, content, file.filename or "anh")


@router.get("/media/{post_id}/{name}")
def get_media(post_id: str, name: str, actor: Actor = Depends(current_actor)):
    path = service.media_path(actor.user_id, post_id, name)
    if path is None:
        raise Refused("Không thấy ảnh.", 404)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/slots/next")
def slots_next(count: int = 6, actor: Actor = Depends(current_actor)):
    settings = service.get_settings(actor.user_id)
    return [
        {"at": timeutil.iso_utc(moment), "label": timeutil.describe(moment, settings["timezone"])}
        for moment in service.next_free_slots(actor.user_id, max(1, min(count, 20)))
    ]
