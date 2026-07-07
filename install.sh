#!/bin/bash
# Simple Samba UI – Erstinstallation (als root)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/install-common.sh
source "${SCRIPT_DIR}/scripts/install-common.sh"

ADMIN_USER="admin"
SHARES_BASE="${SIMPLE_SAMBA_SHARES_BASE:-/srv/shares}"
BIND_HOST="${SIMPLE_SAMBA_BIND_HOST:-}"
BIND_PORT="${SIMPLE_SAMBA_BIND_PORT:-8443}"
HTTP_PORT="${SIMPLE_SAMBA_HTTP_PORT:-8080}"
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
echo "  Installation für Debian 12/13"
echo "========================================"
echo ""

if [[ "${UPGRADE}" != true ]] && [[ -z "${SIMPLE_SAMBA_SHARES_BASE:-}" ]]; then
    detected_base="$(detect_shares_base_from_smb_conf "${SCRIPT_DIR}" 2>/dev/null || true)"
    if [[ -n "${detected_base}" ]]; then
        SHARES_BASE="${detected_base}"
        info "Freigabe-Pfade in smb.conf erkannt – vorgeschlagene Basis: ${SHARES_BASE}"
    fi
fi

if _is_interactive; then
    local_default_host="$(detect_primary_ipv4)"
    read -rp "Basisverzeichnis für Freigaben [${SHARES_BASE}]: " input_base
    SHARES_BASE="${input_base:-${SHARES_BASE}}"

    BIND_HOST="$(prompt_bind_host "${local_default_host}")"
    while ! BIND_HOST="$(validate_bind_host_value "${BIND_HOST}" "${SCRIPT_DIR}")"; do
        warn "Ungültige Bind-Adresse."
        BIND_HOST="$(prompt_bind_host "${local_default_host}")"
    done

    read -rp "HTTPS-Port [${BIND_PORT}]: " input_port
    BIND_PORT="${input_port:-${BIND_PORT}}"

    read -rp "HTTP-Redirect-Port (leitet auf HTTPS um) [${HTTP_PORT}]: " input_http
    HTTP_PORT="${input_http:-${HTTP_PORT}}"

    if [[ "${BIND_PORT}" == "${HTTP_PORT}" ]]; then
        warn "HTTPS- und HTTP-Port dürfen nicht identisch sein – HTTP-Redirect auf 8080."
        HTTP_PORT=8080
        if [[ "${BIND_PORT}" == "8080" ]]; then
            BIND_PORT=8443
        fi
    fi
else
    if [[ -z "${BIND_HOST}" ]]; then
        BIND_HOST="$(detect_primary_ipv4)"
        info "Nicht-interaktiv – lauscht auf LAN-IP ${BIND_HOST}."
    else
        info "Nicht-interaktiv – Bind-Host: ${BIND_HOST}."
    fi
    SHARES_BASE="${SIMPLE_SAMBA_SHARES_BASE:-${SHARES_BASE}}"
    if ! BIND_HOST="$(validate_bind_host_value "${BIND_HOST}" "${SCRIPT_DIR}")"; then
        error "Ungültiger SIMPLE_SAMBA_BIND_HOST: ${SIMPLE_SAMBA_BIND_HOST}"
    fi
    BIND_PORT="${SIMPLE_SAMBA_BIND_PORT:-${BIND_PORT}}"
    HTTP_PORT="${SIMPLE_SAMBA_HTTP_PORT:-${HTTP_PORT}}"
fi

ACCESS_HOST="$(resolve_access_host "${BIND_HOST}")"

ensure_packages
ensure_service_user
copy_application_files "${SCRIPT_DIR}"
setup_python_venv
fix_smb_conf_include

if [[ "${UPGRADE}" == true ]]; then
    info "Bestehende Konfiguration wird beibehalten."
    ensure_https_defaults
else
    ADMIN_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=' | head -c 16)"
    write_initial_config "${ADMIN_USER}" "${ADMIN_PASSWORD}" "${SHARES_BASE}" "${BIND_HOST}" "${BIND_PORT}" "${HTTP_PORT}"
fi

auto_import_smb_shares

install_systemd_units "${SCRIPT_DIR}"
set_permissions
start_services
systemctl reload smbd 2>/dev/null || systemctl restart smbd
verify_installation

echo ""
echo -e "${GREEN}Installation abgeschlossen.${NC}"
echo ""
echo "  HTTPS:    https://${ACCESS_HOST}:${BIND_PORT}/"
if [[ "${HTTP_PORT}" != "${BIND_PORT}" ]]; then
    echo "  HTTP:     http://${ACCESS_HOST}:${HTTP_PORT}/  → Weiterleitung auf HTTPS"
fi
if [[ "${BIND_HOST}" == "0.0.0.0" || "${BIND_HOST}" == "::" ]]; then
    echo "  Lauscht:  ${BIND_HOST} (alle Netzwerk-Interfaces)"
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
echo "  Zertifikat:      selbstsigniert (${CONFIG_DIR}/tls/) – Browser-Warnung ist normal"
echo ""
