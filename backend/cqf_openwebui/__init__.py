"""Chatbot website + Hop thu + Kien thuc + Lich dang, chay ben trong Open WebUI (khong fork, khong sua file cua Open WebUI).

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

    import logging

    try:
        from .lich import start

        start()  # Lich dang: sends scheduled WordPress posts at their time
    except Exception:  # noqa: BLE001 - the chatbot keeps working even if Lich dang cannot start
        logging.getLogger("cqf_openwebui").exception("Lich dang could not start")
