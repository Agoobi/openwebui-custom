"""Nha cung cap "hermes": chatbot dung chung LLM ma Hermes (cung VPS) dang dung.

Doc moi lan goi (doi model ben Hermes la chatbot doi theo): <HERMES_HOME>/config.yaml > model {default, base_url,
key_env} va key trong env / .coquifly.env / .env cua Hermes. Chi doc, khong ghi gi ben Hermes. Key khong bao gio tra
ra trang Chatbot (summary() chi co model va dia chi API).
"""
import os
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
# Hermes provider khong ghi base_url: dia chi API chuan OpenAI cua nha cung cap do
KNOWN = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
    "deepseek": "https://api.deepseek.com/v1",
}
KEY_ENV = {"openrouter": "OPENROUTER_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
           "google": "GOOGLE_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}


class HermesLLMError(RuntimeError):
    pass


def _dotenv(path):
    out = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip().removeprefix("export ").strip()] = v.strip().strip("'\"")
    return out


def resolve():
    """{"base_url", "api_key", "model"} Hermes dang dung. Loi -> HermesLLMError (noi ro thieu gi)."""
    import yaml

    try:
        cfg = yaml.safe_load((HERMES_HOME / "config.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        raise HermesLLMError(f"Không đọc được cấu hình Hermes ({HERMES_HOME}/config.yaml).")
    m = cfg.get("model") or {}
    if isinstance(m, str):
        m = {"default": m}
    provider = str(m.get("provider") or "").lower()
    base_url = (m.get("base_url") or KNOWN.get(provider) or "").rstrip("/")
    model = m.get("default") or m.get("model") or ""
    if not base_url or not model:
        raise HermesLLMError(f"Hermes dùng nhà cung cấp '{provider or '?'}' chưa hỗ trợ (cần địa chỉ API chuẩn OpenAI).")
    key_env = m.get("key_env") or KEY_ENV.get(provider) or ""
    key = m.get("api_key") or ""
    if not key and key_env:
        env = {**_dotenv(HERMES_HOME / ".env"), **_dotenv(HERMES_HOME / ".coquifly.env")}
        key = os.environ.get(key_env) or env.get(key_env) or ""
    if not key:
        raise HermesLLMError(f"Không thấy API key của Hermes ({key_env or 'chưa khai báo key_env'}).")
    return {"base_url": base_url, "api_key": key, "model": model}


def summary():
    """Cho trang Chatbot: model + dia chi API (khong co key)."""
    try:
        r = resolve()
        return {"ok": True, "model": r["model"], "base_url": r["base_url"]}
    except HermesLLMError as e:
        return {"ok": False, "error": str(e)}


def effective(llm):
    """Cau hinh LLM that su de goi: provider "hermes" -> lay cua Hermes (giu temperature cua chatbot)."""
    if (llm or {}).get("provider") != "hermes":
        return llm or {}
    return {**resolve(), "temperature": llm.get("temperature", 0.3)}
