#!/bin/bash
# HTTPS für Simple Samba UI (Migration / Zertifikat erneuern)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/install-common.sh
source "${SCRIPT_DIR}/install-common.sh"

require_root

echo ""
echo "========================================"
echo "  Simple Samba UI – HTTPS"
echo "========================================"
echo ""

ensure_https_defaults

ACCESS_HOST="$(resolve_access_host "$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['bind_host'])")")"
BIND_PORT="$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['bind_port'])")"
HTTP_PORT="$(python3 -c "import json; c=json.load(open('${CONFIG_FILE}')); print(c.get('http_port', 8080))")"

systemctl restart simple-samba-ui

echo ""
echo -e "${GREEN}HTTPS aktiv.${NC}"
echo ""
echo "  URL: https://${ACCESS_HOST}:${BIND_PORT}/"
if [[ "${HTTP_PORT}" != "${BIND_PORT}" ]]; then
    echo "  HTTP-Redirect: http://${ACCESS_HOST}:${HTTP_PORT}/ → HTTPS"
fi
echo "  Zertifikat: ${CONFIG_DIR}/tls/server.crt (selbstsigniert – Browser-Warnung ist normal)"
echo ""
