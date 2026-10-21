"""python -m cqf_openwebui serve [--host ...] [--port ...]: chay Open WebUI goc kem router /api/v1/cqf.

Lam dung nhu "open-webui serve"; chi gan them router truoc khi uvicorn nap "open_webui.main:app" (cung module trong
sys.modules nen app da co router). Can UVICORN_WORKERS=1 (mac dinh): worker phu nap lai app se mat router.
"""
import base64, os, random, sys


def main():
    import open_webui as cli  # goi CLI cua Open WebUI (nhe, chua nap app)

    # Giong het "open-webui serve" TRUOC khi import open_webui.main: FROM_INIT_PY quyet dinh thu muc giao dien /
    # static cua ban cai pip (thieu -> trang chu va /static 404); WEBUI_SECRET_KEY can luc import.
    os.environ["FROM_INIT_PY"] = "true"
    if os.getenv("WEBUI_SECRET_KEY") is None:
        if not cli.KEY_FILE.exists():
            length = int(os.getenv("WEBUI_SECRET_KEY_LENGTH", cli.DEFAULT_SECRET_KEY_LENGTH))
            cli.KEY_FILE.write_bytes(base64.b64encode(random.randbytes(length)))
        os.environ["WEBUI_SECRET_KEY"] = cli.KEY_FILE.read_text()
    if int(os.getenv("UVICORN_WORKERS", "1") or 1) != 1:
        sys.exit("cqf_openwebui can UVICORN_WORKERS=1 (worker phu se khong co /api/v1/cqf).")

    import open_webui.main as owui_main

    from . import attach

    attach(owui_main.app)
    sys.argv = ["open-webui", *sys.argv[1:]]
    cli.app()


if __name__ == "__main__":
    main()
