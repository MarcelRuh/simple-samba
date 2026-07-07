#!/bin/bash
# Startet HTTP-Redirect (Hintergrund) und Gunicorn mit HTTPS (Vordergrund)
set -euo pipefail

INSTALL_DIR="/opt/simple-samba-ui"
CONFIG_FILE="/etc/simple-samba-ui/config.json"
cd "${INSTALL_DIR}"

REDIRECT_PID=""
cleanup() {
    if [[ -n "${REDIRECT_PID}" ]]; then
        kill "${REDIRECT_PID}" 2>/dev/null || true
        wait "${REDIRECT_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT TERM INT

if [[ -f "${CONFIG_FILE}" ]]; then
    if "${INSTALL_DIR}/venv/bin/python3" - <<'PY'
import json
import sys
from pathlib import Path

cfg = json.loads(Path("/etc/simple-samba-ui/config.json").read_text(encoding="utf-8"))
if not cfg.get("tls_enabled"):
    sys.exit(1)
http_port = int(cfg.get("http_port", 0) or 0)
https_port = int(cfg.get("bind_port", 0) or 0)
if http_port <= 0 or http_port == https_port:
    sys.exit(1)
sys.exit(0)
PY
    then
        "${INSTALL_DIR}/venv/bin/python3" "${INSTALL_DIR}/scripts/http-redirect-server.py" &
        REDIRECT_PID=$!
    fi
fi

exec "${INSTALL_DIR}/venv/bin/gunicorn" -c "${INSTALL_DIR}/gunicorn.conf.py" wsgi:app
