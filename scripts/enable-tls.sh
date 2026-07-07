#!/bin/bash
# HTTPS für Simple Samba UI aktivieren (selbstsigniertes Zertifikat)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/install-common.sh
source "${SCRIPT_DIR}/install-common.sh"

require_root

TLS_PORT="${SIMPLE_SAMBA_TLS_PORT:-}"

echo ""
echo "========================================"
echo "  Simple Samba UI – HTTPS aktivieren"
echo "========================================"
echo ""

ensure_tls_certificates

python3 - <<'PY'
import json
from pathlib import Path

config_path = Path("/etc/simple-samba-ui/config.json")
cfg = json.loads(config_path.read_text(encoding="utf-8"))
cfg["tls_enabled"] = True
cfg.setdefault("tls_cert_file", "/etc/simple-samba-ui/tls/server.crt")
cfg.setdefault("tls_key_file", "/etc/simple-samba-ui/tls/server.key")
config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

chown samba-ui:samba-ui "${CONFIG_FILE}" 2>/dev/null || true
chmod 600 "${CONFIG_FILE}"

ACCESS_HOST="$(resolve_access_host "$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['bind_host'])")")"
BIND_PORT="$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['bind_port'])")"

systemctl restart simple-samba-ui

echo ""
echo -e "${GREEN}HTTPS aktiviert.${NC}"
echo ""
echo "  URL: https://${ACCESS_HOST}:${BIND_PORT}/"
echo "  Zertifikat: ${CONFIG_DIR}/tls/server.crt (selbstsigniert – Browser-Warnung ist normal)"
echo ""
echo "  Ordner-Downloads im Datei-Explorer nutzen dann die Ordnerstruktur statt ZIP."
echo ""
