#!/usr/bin/env bash
# Cai openwebui-custom vao Open WebUI cai bang pip + systemd. Chay lai an toan; chay lai sau moi lan nang cap
# Open WebUI (pip ghi de thu muc static).
#
#   sudo deploy/install.sh [duong-dan-venv] [ten-service]
#   mac dinh: /opt/open-webui/venv  open-webui
#
# Viec lam:
#   1. Trang tinh: loader.js, custom.css, hop-thu/, chatbot/, kien-thuc/, cqf/ vao thu muc static cua Open WebUI
#      (ca <goi>/static va <goi>/frontend/static: luc khoi dong Open WebUI chep loader.js tu frontend sang static).
#   2. Backend: file cqf_openwebui.pth trong venv tro toi <repo>/backend (khong chep, khong sua file Open WebUI).
#   3. systemd drop-in: chay "python -m cqf_openwebui serve" thay "open-webui serve" (= Open WebUI goc + /api/v1/cqf).
#      Go: xoa /etc/systemd/system/<service>.service.d/cqf.conf, systemctl daemon-reload, restart.
#   4. poppler-utils (doc PDF) neu may chua co.
set -euo pipefail

VENV="${1:-/opt/open-webui/venv}"
SERVICE="${2:-open-webui}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/static"
EXPECTED="0.11.4"
PY="$VENV/bin/python"

PKG="$("$PY" -c 'import open_webui, os; print(os.path.dirname(open_webui.__file__))')"
SITE="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
VERSION="$("$PY" -c 'import importlib.metadata as m; print(m.version("open-webui"))')"
if [ "$VERSION" != "$EXPECTED" ]; then
  echo "Canh bao: Open WebUI $VERSION, ban tuy bien kiem voi $EXPECTED. Kiem tra lai sau khi cai." >&2
fi

# 1. trang tinh
for dir in "$PKG/static" "$PKG/frontend/static"; do
  [ -d "$dir" ] || continue
  for f in custom.css loader.js; do
    [ -f "$dir/$f" ] && [ ! -f "$dir/$f.orig" ] && cp -p "$dir/$f" "$dir/$f.orig"
    install -m 0644 "$SRC/$f" "$dir/$f"
  done
  for page in hop-thu chatbot kien-thuc cqf; do
    install -d -m 0755 "$dir/$page"
    find "$SRC/$page" -maxdepth 1 -type f \( -name '*.html' -o -name '*.js' -o -name '*.css' \) -exec install -m 0644 {} "$dir/$page/" \;
  done
  rm -f "$dir/hop-thu/config.json"  # ban cu (Hop thu doc Hermes): gio cung origin, khong can
  echo "trang tinh -> $dir"
done

# 2. backend
echo "$REPO/backend" > "$SITE/cqf_openwebui.pth"
"$PY" -c 'import cqf_openwebui' && echo "backend: $REPO/backend (qua $SITE/cqf_openwebui.pth)"

# 3. systemd: chay Open WebUI kem /api/v1/cqf
UNIT_DIR="/etc/systemd/system/$SERVICE.service.d"
install -d -m 0755 "$UNIT_DIR"
ARGS="$(systemctl cat "$SERVICE" | grep -v '^#' | sed -n 's/^ExecStart=.* serve\(.*\)$/\1/p' | tail -1)"
cat > "$UNIT_DIR/cqf.conf" <<EOF
# openwebui-custom: Open WebUI goc + /api/v1/cqf (chatbot website, Hop thu, Kien thuc). Xoa file nay de go.
[Service]
ExecStart=
ExecStart=$PY -m cqf_openwebui serve${ARGS:- --host 127.0.0.1 --port 8080}
EOF
systemctl daemon-reload

# 4. doc PDF
if ! command -v pdftotext >/dev/null; then
  if command -v dnf >/dev/null; then dnf install -y -q poppler-utils || true
  elif command -v apt-get >/dev/null; then apt-get install -y -qq poppler-utils || true; fi
fi

systemctl restart "$SERVICE"
for i in $(seq 1 45); do
  if curl -fsS -o /dev/null http://127.0.0.1:8080/health; then
    if curl -fsS http://127.0.0.1:8080/static/loader.js | grep -q "sidebar-cqf-" \
      && [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/v1/cqf/status)" = "401" ]; then
      echo "ok: Open WebUI $VERSION + openwebui-custom (/api/v1/cqf)"
      exit 0
    fi
  fi
  sleep 2
done
echo "Open WebUI chua chay dung ban tuy bien: xem journalctl -u $SERVICE" >&2
exit 1
