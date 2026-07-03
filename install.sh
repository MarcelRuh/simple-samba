#!/bin/bash
# Simple Samba UI – Erstinstallation (als root)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/install-common.sh
source "${SCRIPT_DIR}/scripts/install-common.sh"

ADMIN_USER="admin"
SHARES_BASE="${SIMPLE_SAMBA_SHARES_BASE:-/srv/shares}"
BIND_HOST="${SIMPLE_SAMBA_BIND_HOST:-0.0.0.0}"
BIND_PORT="${SIMPLE_SAMBA_BIND_PORT:-8080}"
UPGRADE=false

_is_interactive() {
    [[ -t 0 ]] && [[ "${SIMPLE_SAMBA_NONINTERACTIVE:-}" != "1" ]]
}

require_root

if [[ -f "${CONFIG_FILE}" ]]; then
    if _is_interactive; then
        warn "Bestehende Installation erkannt."
        read -rp "Upgrade/Reinstall durchführen? Konfiguration bleibt erhalten. (ja/nein) [ja]: " up
        up="${up:-ja}"
        [[ "${up}" == "ja" ]] && UPGRADE=true
    else
        info "Bestehende Installation – führe Upgrade durch (Konfiguration bleibt erhalten)."
        UPGRADE=true
    fi
fi

echo ""
echo "========================================"
echo "  Simple Samba UI v${APP_VERSION}"
echo "  Installation für Debian 13"
echo "========================================"
echo ""

if _is_interactive; then
    local_default_host="$(detect_primary_ipv4)"
    read -rp "Basisverzeichnis für Freigaben [${SHARES_BASE}]: " input_base
    SHARES_BASE="${input_base:-${SHARES_BASE}}"

    read -rp "Bind-Host [${BIND_HOST}] (0.0.0.0 = alle Interfaces, erreichbar unter ${local_default_host}): " input_host
    BIND_HOST="${input_host:-${BIND_HOST}}"

    read -rp "Bind-Port [${BIND_PORT}]: " input_port
    BIND_PORT="${input_port:-${BIND_PORT}}"
else
    info "Nicht-interaktiv – lauscht auf allen Interfaces (0.0.0.0)."
    SHARES_BASE="${SIMPLE_SAMBA_SHARES_BASE:-${SHARES_BASE}}"
    BIND_HOST="${SIMPLE_SAMBA_BIND_HOST:-${BIND_HOST}}"
    BIND_PORT="${SIMPLE_SAMBA_BIND_PORT:-${BIND_PORT}}"
fi

ACCESS_HOST="$(resolve_access_host "${BIND_HOST}")"

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
echo "  URL:      http://${ACCESS_HOST}:${BIND_PORT}/"
if [[ "${BIND_HOST}" == "0.0.0.0" || "${BIND_HOST}" == "::" ]]; then
    echo "  Lauscht:  ${BIND_HOST}:${BIND_PORT} (alle Netzwerk-Interfaces)"
fi
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
