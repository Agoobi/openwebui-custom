"""API /api/v1/cqf/lead of Săn lead, mounted by cqf_openwebui.router.

People: signed in to Open WebUI (any approved user sees and works the leads; admins change settings and the key).
Agent (Hermes on the same machine, skill san-lead-b2b): header X-Lead-Agent-Token from <DATA_DIR>/cqf/lead/agent.json.

    GET  /me                              settings, key status (never the key), lists, rules, last runs
    PUT  /settings                        (admin)
    PUT  /apify-key  DELETE /apify-key    (admin) save after Apify accepts it / remove
    POST /apify-key/check                 plan, usage this month
    GET  /opportunities?state&industry&kind&province&q&min_score&sort&limit&offset
    GET/PATCH/DELETE /opportunities/{id}  PATCH: state, note (people only); DELETE: admin
    GET  /people?...   PATCH/DELETE /people/{id}
    GET  /export/{opportunities|people}.csv
    GET  /runs
  Agent only:
    GET  /agent/config                    Apify key, settings, LLM, lists
    POST /agent/seen/check {urls}         links not read before      POST /agent/seen {items:[{url, verdict}]}
    POST /agent/opportunities {items, run_id}   POST /agent/people {items, run_id}
    POST /agent/opportunities/{id}/contact {website, phones, emails, address, tax_code, linkedin_company, sources}
    POST /agent/runs {trigger}            PATCH /agent/runs/{id} {status, stats, cost_usd, message}
"""

import hmac

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel

from . import config, service
from .service import Actor, Refused

router = APIRouter()
config.agent_token()  # agent.json exists from the first start: the skill reads it before its first call


def _token_of(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get("token")


async def current_actor(request: Request) -> Actor:
    agent_token = request.headers.get("x-lead-agent-token")
    if agent_token:
        if hmac.compare_digest(agent_token, config.agent_token()):
            return Actor("agent", "Agent", role="agent", is_agent=True)
        raise Refused("Token của agent không đúng.", 401)
    token = _token_of(request)
    if not token:
        raise Refused("Chưa đăng nhập Open WebUI.", 401)
    from open_webui.utils.auth import get_verified_user_by_token

    user = await get_verified_user_by_token(token, getattr(request.app.state, "redis", None))
    if user is None:
        raise Refused("Phiên đăng nhập Open WebUI đã hết, đăng nhập lại.", 401)
    return Actor(user.id, user.name or user.email or "Người dùng", role=user.role)


def agent_only(actor: Actor = Depends(current_actor)) -> Actor:
    if not actor.is_agent:
        raise Refused("Chỉ agent (token trong agent.json) mới gọi được đường này.", 403)
    return actor


def people_only(actor: Actor = Depends(current_actor)) -> Actor:
    if actor.is_agent:
        raise Refused("Đường này dành cho người dùng Open WebUI.", 403)
    return actor


# ---------------------------------------------------------------- page


@router.get("/me")
def me(actor: Actor = Depends(people_only)):
    return {
        "user": {"id": actor.user_id, "name": actor.name, "is_admin": actor.is_admin},
        "settings": service.get_settings(),
        "apify": service.key_status(),
        "proxy": service.proxy_status(),
        "month_cost_usd": service.month_cost(),
        "industries": config.INDUSTRIES,
        "industry_short": config.INDUSTRY_SHORT,
        "kinds": config.KINDS,
        "states": config.STATES,
        "plant_status": config.PLANT_STATUS,
        "role_groups": config.ROLE_GROUPS,
        "provinces": config.PROVINCES,
        "other_provinces": config.OTHER_PROVINCES,
        "rules": config.RULES,
        "runs": service.list_runs(5),
        "agent_file": str(config.AGENT_FILE),
    }


class KeyIn(BaseModel):
    key: str


@router.put("/apify-key")
def put_key(body: KeyIn, actor: Actor = Depends(people_only)):
    return service.save_key(actor, body.key)


@router.delete("/apify-key")
def delete_key(actor: Actor = Depends(people_only)):
    return service.delete_key(actor)


@router.post("/apify-key/check")
def check_key(actor: Actor = Depends(people_only)):
    service.check_key()
    return service.key_status()


class ProxyIn(BaseModel):
    value: str


@router.put("/proxy")
def put_proxy(body: ProxyIn, actor: Actor = Depends(people_only)):
    return service.save_proxy(actor, body.value)


@router.delete("/proxy")
def delete_proxy(actor: Actor = Depends(people_only)):
    return service.delete_proxy(actor)


@router.post("/proxy/check")
def check_proxy(actor: Actor = Depends(people_only)):
    if not actor.is_admin:
        raise service.Refused("Chỉ quản trị viên.", 403)
    service.check_proxy()
    return service.proxy_status()


@router.put("/settings")
def put_settings(body: dict, actor: Actor = Depends(people_only)):
    return service.save_settings(actor, body)


def _filters(request: Request) -> dict:
    return dict(request.query_params)


@router.get("/opportunities")
def opportunities(request: Request, _: Actor = Depends(current_actor)):
    return service.list_opportunities(_filters(request))


@router.get("/opportunities/{opp_id}")
def opportunity(opp_id: str, _: Actor = Depends(current_actor)):
    return service.get_opportunity(opp_id)


class StateIn(BaseModel):
    state: str | None = None
    note: str | None = None


@router.patch("/opportunities/{opp_id}")
def patch_opportunity(opp_id: str, body: StateIn, actor: Actor = Depends(people_only)):
    return service.patch_opportunity(actor, opp_id, body.model_dump(exclude_unset=True))


@router.delete("/opportunities/{opp_id}")
def delete_opportunity(opp_id: str, actor: Actor = Depends(people_only)):
    service.delete_item(actor, "opportunities", opp_id)
    return {"ok": True}


@router.get("/people")
def people(request: Request, _: Actor = Depends(current_actor)):
    return service.list_people(_filters(request))


@router.patch("/people/{person_id}")
def patch_person(person_id: str, body: StateIn, actor: Actor = Depends(people_only)):
    return service.patch_person(actor, person_id, body.model_dump(exclude_unset=True))


@router.delete("/people/{person_id}")
def delete_person(person_id: str, actor: Actor = Depends(people_only)):
    service.delete_item(actor, "people", person_id)
    return {"ok": True}


@router.get("/export/{table}.csv")
def export(table: str, _: Actor = Depends(people_only)):
    if table not in ("opportunities", "people"):
        raise Refused("Chỉ xuất được opportunities hoặc people.", 404)
    name = "co-hoi" if table == "opportunities" else "nguoi-lien-he"
    return Response(service.export_csv(table), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="san-lead-{name}.csv"'})


@router.get("/runs")
def runs(limit: int = 30, _: Actor = Depends(current_actor)):
    return service.list_runs(limit)


# ---------------------------------------------------------------- agent


@router.get("/agent/config")
def agent_config(_: Actor = Depends(agent_only)):
    return service.agent_config()


class UrlsIn(BaseModel):
    urls: list[str]


@router.post("/agent/seen/check")
def seen_check(body: UrlsIn, _: Actor = Depends(agent_only)):
    return {"unseen": service.unseen(body.urls)}


class ItemsIn(BaseModel):
    items: list
    run_id: str | None = None


@router.post("/agent/seen")
def seen_mark(body: ItemsIn, _: Actor = Depends(agent_only)):
    return {"marked": service.mark_seen(body.items)}


@router.post("/agent/opportunities")
def agent_opportunities(body: ItemsIn, _: Actor = Depends(agent_only)):
    return service.upsert_opportunities(body.items, body.run_id)


@router.post("/agent/opportunities/{opp_id}/contact")
def agent_contact(opp_id: str, body: dict, _: Actor = Depends(agent_only)):
    return service.set_company_contact(opp_id, body)


@router.post("/agent/people")
def agent_people(body: ItemsIn, _: Actor = Depends(agent_only)):
    return service.upsert_people(body.items, body.run_id)


class RunIn(BaseModel):
    trigger: str = ""


@router.post("/agent/runs")
def agent_start_run(body: RunIn, _: Actor = Depends(agent_only)):
    return service.start_run(body.trigger)


@router.patch("/agent/runs/{run_id}")
def agent_finish_run(run_id: str, body: dict, _: Actor = Depends(agent_only)):
    return service.finish_run(run_id, body)
