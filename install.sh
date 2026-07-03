#!/bin/bash
# Simple Samba UI – Erstinstallation (als root)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/install-common.sh
source "${SCRIPT_DIR}/scripts/install-common.sh"

ADMIN_USER="admin"
SHARES_BASE="/srv/shares"
BIND_HOST="127.0.0.1"
BIND_PORT="8080"
UPGRADE=false

require_root

if [[ -f "${CONFIG_FILE}" ]]; then
    warn "Bestehende Installation erkannt."
    read -rp "Upgrade/Reinstall durchführen? Konfiguration bleibt erhalten. (ja/nein) [ja]: " up
    up="${up:-ja}"
    [[ "${up}" == "ja" ]] && UPGRADE=true
fi

echo ""
echo "========================================"
echo "  Simple Samba UI v${APP_VERSION}"
echo "  Installation für Debian 13"
echo "========================================"
echo ""

read -rp "Basisverzeichnis für Freigaben [${SHARES_BASE}]: " input_base
SHARES_BASE="${input_base:-${SHARES_BASE}}"

read -rp "Bind-Host [${BIND_HOST}]: " input_host
BIND_HOST="${input_host:-${BIND_HOST}}"

read -rp "Bind-Port [${BIND_PORT}]: " input_port
BIND_PORT="${input_port:-${BIND_PORT}}"

ensure_packages
ensure_service_user
copy_application_files "${SCRIPT_DIR}"
setup_python_venv
fix_smb_conf_include

if [[ "${UPGRADE}" == true ]]; then
    info "Bestehende Konfiguration wird beibehalten."
else
    ADMIN_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=' | head -c 16)"
    write_initial_config "${ADMIN_USER}" "${ADMIN_PASSWORD}" "${SHARES_BASE}" "${BIND_HOST}" "${BIND_PORT}"
fi

install_systemd_units "${SCRIPT_DIR}"
set_permissions
start_services
systemctl reload smbd 2>/dev/null || systemctl restart smbd
verify_installation

echo ""
echo -e "${GREEN}Installation abgeschlossen.${NC}"
echo ""
echo "  URL:      http://${BIND_HOST}:${BIND_PORT}/"
echo "  Benutzer: ${ADMIN_USER}"
if [[ "${UPGRADE}" != true ]]; then
    echo "  Passwort: ${ADMIN_PASSWORD}"
    echo "  (auch in ${CONFIG_DIR}/initial-password.txt)"
fi
echo ""
echo "  Quellverzeichnis: ${SCRIPT_DIR}"
echo "  Deployment:      ${INSTALL_DIR}"
echo "  Update:          bash ${SCRIPT_DIR}/update.sh"
echo ""
