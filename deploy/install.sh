#!/usr/bin/env bash
# Cai custom.css + loader.js vao Open WebUI cai bang pip (systemd). Chay lai an toan; chay lai sau moi lan nang cap
# Open WebUI (pip ghi de thu muc static).
#
#   sudo deploy/install.sh [duong-dan-venv] [ten-service]
#   mac dinh: /opt/open-webui/venv  open-webui
#
# Open WebUI phuc vu /static tu <goi>/static va luc khoi dong chep loader.js tu <goi>/frontend/static sang do,
# nen file duoc ghi vao ca 2 cho. Ban goc duoc giu o *.orig (lan dau).
set -euo pipefail

VENV="${1:-/opt/open-webui/venv}"
SERVICE="${2:-open-webui}"
SRC="$(cd "$(dirname "$0")/.." && pwd)/static"
EXPECTED="0.11.4"

PKG="$("$VENV/bin/python" -c 'import open_webui, os; print(os.path.dirname(open_webui.__file__))')"
VERSION="$("$VENV/bin/python" -c 'import importlib.metadata as m; print(m.version("open-webui"))')"
if [ "$VERSION" != "$EXPECTED" ]; then
  echo "Canh bao: Open WebUI $VERSION, ban tuy bien kiem voi $EXPECTED. Kiem tra lai giao dien sau khi cai." >&2
fi

for dir in "$PKG/static" "$PKG/frontend/static"; do
  [ -d "$dir" ] || continue
  for f in custom.css loader.js; do
    [ -f "$dir/$f" ] && [ ! -f "$dir/$f.orig" ] && cp -p "$dir/$f" "$dir/$f.orig"
    install -m 0644 "$SRC/$f" "$dir/$f"
  done
  echo "da cai vao $dir"
done

systemctl restart "$SERVICE"
for i in $(seq 1 30); do
  if curl -fsS -o /dev/null http://127.0.0.1:8080/static/loader.js; then
    curl -fsS http://127.0.0.1:8080/static/loader.js | grep -q "cqf-open-chat" && echo "ok: Open WebUI $VERSION dang phuc vu ban tuy bien" && exit 0
  fi
  sleep 2
done
echo "Open WebUI chua phuc vu loader.js moi: xem journalctl -u $SERVICE" >&2
exit 1
