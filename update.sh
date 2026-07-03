#!/bin/bash
# Simple Samba UI – Update auf aktuelle Version (als root)
# Kopiert aus dem Quellverzeichnis nach /opt/simple-samba-ui
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/install-common.sh
source "${SCRIPT_DIR}/scripts/install-common.sh"

require_root

echo ""
echo "========================================"
echo "  Simple Samba UI Update → v${APP_VERSION}"
echo "========================================"
echo ""

ensure_service_user
copy_application_files "${SCRIPT_DIR}"
setup_python_venv
fix_smb_conf_include 2>/dev/null || true
auto_import_smb_shares
install_systemd_units "${SCRIPT_DIR}"
set_permissions
start_services
systemctl restart smbd nmbd 2>/dev/null || true
verify_installation

echo ""
echo -e "${GREEN}Update abgeschlossen.${NC} Version: v${APP_VERSION}"
echo ""
