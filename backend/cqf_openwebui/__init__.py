"""Chatbot website + Hop thu + Kien thuc, chay ben trong Open WebUI (khong fork, khong sua file cua Open WebUI).

attach(app) gan router /api/v1/cqf vao app cua Open WebUI, dat TRUOC route giao dien (mount "/" bat moi duong dan).
Khoi dong: python -m cqf_openwebui serve --host 127.0.0.1 --port 8080 (thay cho "open-webui serve").
"""

PREFIX = "/api/v1/cqf"


def attach(app):
    from .router import router

    if any(getattr(r, "path", "").startswith(PREFIX) for r in app.router.routes):
        return  # da gan
    before = len(app.router.routes)
    app.include_router(router, prefix=PREFIX, tags=["cqf"])
    added = app.router.routes[before:]
    del app.router.routes[before:]
    app.router.routes[0:0] = added
