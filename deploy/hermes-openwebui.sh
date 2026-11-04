#!/usr/bin/env bash
# Hermes tra loi trong Open WebUI bang Markdown.
#
# Open WebUI goi Hermes qua API server (chuan OpenAI). Hermes mac dinh coi API server la "khong ro cach hien thi, chi chu
# thuong, khong Markdown", nen bang, anh, chu dam bi bo (vd preview bai cua Lich dang). Open WebUI hien Markdown day du,
# nen script nay thay goi y do bang khoa platform_hints.api_server.replace trong config.yaml cua Hermes (Hermes co san
# khoa nay). Chi anh huong cac cuoc chat qua API server (Open WebUI); Telegram, Zalo, chatbot website khong doi.
#
#   sudo deploy/hermes-openwebui.sh [HERMES_HOME]        mac dinh /root/.hermes
#   Go: hermes config unset platform_hints.api_server
set -euo pipefail

HOME_DIR="${1:-${HERMES_HOME:-/root/.hermes}}"
PY="$HOME_DIR/hermes-agent/venv/bin/python"
CLI="$HOME_DIR/hermes-agent/hermes"
[ -x "$PY" ] && [ -f "$CLI" ] || { echo "Khong thay Hermes o $HOME_DIR" >&2; exit 1; }

HINT="You're responding inside Open WebUI, which renders Markdown fully: headings, bold, lists, tables, links and images ![alt](url). Use Markdown where it helps the reader (tables for facts, article previews, step lists) and keep ordinary conversation short and natural. When a tool gives you Markdown meant for the user (for example preview_markdown of a blog post), paste it verbatim without rewriting or dropping parts. Relative links such as /#lich-dang/post=<id> open inside Open WebUI. File/media delivery: images referenced as MEDIA:/absolute/path tags (.png/.jpg/.jpeg/.gif/.webp/.bmp, up to 5MB) are inlined as base64 data URLs in responses on the chat, completions, and responses endpoints. Non-image files are not intercepted: state the plain file path instead of a MEDIA: tag."

cp -p "$HOME_DIR/config.yaml" "$HOME_DIR/config.yaml.bak-openwebui-$(date -u +%Y%m%dT%H%M%SZ)"
cd "$HOME_DIR"
HERMES_HOME="$HOME_DIR" "$PY" "$CLI" config set platform_hints.api_server.replace "$HINT"
echo "ok: Hermes tra loi Markdown trong Open WebUI (platform_hints.api_server)"
