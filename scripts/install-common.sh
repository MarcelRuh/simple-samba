#!/bin/bash
# Gemeinsame Install-/Update-Logik für Simple Samba UI
# Quellverzeichnis (Clone) → Deployment nach /opt/simple-samba-ui

_INSTALL_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_VERSION="$(PYTHONPATH="${_INSTALL_COMMON_DIR}" python3 -c "from app import __version__; print(__version__)" 2>/dev/null || echo "unknown")"
INSTALL_DIR="/opt/simple-samba-ui"
CONFIG_DIR="/etc/simple-samba-ui"
CONFIG_FILE="${CONFIG_DIR}/config.json"
SAMBA_SHARES_FILE="/etc/samba/smb-shares.conf"
SMB_CONF="/etc/samba/smb.conf"
BACKUP_DIR="/var/backups/simple-samba-ui"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}▸${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
error() { echo -e "${RED}✖${NC} $*" >&2; }

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        error "Dieses Script muss als root ausgeführt werden."
        exit 1
    fi
}

detect_primary_ipv4() {
    local ip=""
    if command -v ip >/dev/null 2>&1; then
        ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }}')"
    fi
    if [[ -z "${ip}" ]]; then
        ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    fi
    echo "${ip:-127.0.0.1}"
}

resolve_access_host() {
    local bind_host="${1:-0.0.0.0}"
    case "${bind_host}" in
        0.0.0.0|::|::0)
            detect_primary_ipv4
            ;;
        *)
            echo "${bind_host}"
            ;;
    esac
}

prompt_bind_host() {
    local default_ip="${1:-$(detect_primary_ipv4)}"
    local choice

    echo ""
    echo "  Bind-Adresse für die Web-UI:"
    echo "    1) LAN-IP (${default_ip})  [empfohlen]"
    echo "    2) Nur lokal (127.0.0.1) – Zugriff per SSH-Tunnel"
    echo "    3) Alle Interfaces (0.0.0.0) – im gesamten LAN erreichbar"
    echo ""
    read -rp "Auswahl [1]: " choice
    choice="${choice:-1}"
    case "${choice}" in
        1|"")
            echo "${default_ip}"
            ;;
        2)
            echo "127.0.0.1"
            ;;
        3)
            echo "0.0.0.0"
            ;;
        *)
            warn "Ungültige Auswahl – nutze LAN-IP ${default_ip}"
            echo "${default_ip}"
            ;;
    esac
}

validate_bind_host_value() {
    local host="$1"
    local src="${2:-${_INSTALL_COMMON_DIR}}"
    PYTHONPATH="${src}" python3 -c "
from app.validators import validate_bind_host, ValidationError
import sys
try:
    print(validate_bind_host(sys.argv[1]))
except ValidationError:
    sys.exit(1)
" "${host}" 2>/dev/null
}

ensure_packages() {
    info "Prüfe Systempakete …"
    local pkgs=(python3 python3-venv python3-pip git ca-certificates wget sudo samba samba-common-bin)
    local missing=()
    for pkg in "${pkgs[@]}"; do
        dpkg -s "${pkg}" &>/dev/null || missing+=("${pkg}")
    done
    if ((${#missing[@]})); then
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
    fi
}

ensure_service_user() {
    if ! id samba-ui &>/dev/null; then
        info "Lege Systembenutzer samba-ui an …"
        useradd --system --home /var/lib/samba-ui --shell /usr/sbin/nologin samba-ui
    fi
    mkdir -p /var/lib/samba-ui
    chown samba-ui:samba-ui /var/lib/samba-ui
}

copy_application_files() {
    local src="$1"
    info "Installiere App v${APP_VERSION} nach ${INSTALL_DIR} …"
    mkdir -p "${INSTALL_DIR}"
    cp -a "${src}/app" "${src}/scripts" "${src}/etc" \
          "${src}/requirements.txt" "${src}/wsgi.py" "${src}/gunicorn.conf.py" \
          "${src}/README.md" "${INSTALL_DIR}/"
    if [[ -f "${src}/update.sh" ]]; then
        cp -a "${src}/update.sh" "${INSTALL_DIR}/"
    fi
}

setup_python_venv() {
    info "Python-venv einrichten …"
    if [[ ! -d "${INSTALL_DIR}/venv" ]]; then
        python3 -m venv "${INSTALL_DIR}/venv"
    fi
    "${INSTALL_DIR}/venv/bin/pip" install -q --upgrade pip
    "${INSTALL_DIR}/venv/bin/pip" install -q -r "${INSTALL_DIR}/requirements.txt"
}

ensure_samba_shares_file() {
    if [[ ! -f "${SAMBA_SHARES_FILE}" ]]; then
        info "Erstelle ${SAMBA_SHARES_FILE} …"
        cat >"${SAMBA_SHARES_FILE}" <<'EOF'
# Verwaltet von Simple Samba UI
# Keine Freigaben definiert.
EOF
        chmod 644 "${SAMBA_SHARES_FILE}"
    fi
}

fix_smb_conf_include() {
    ensure_samba_shares_file
    if [[ ! -f "${SMB_CONF}" ]]; then
        warn "smb.conf nicht gefunden – Samba-Include übersprungen."
        return 0
    fi
    local py_src="${INSTALL_DIR}"
    [[ -d "${py_src}/app" ]] || py_src="${SCRIPT_DIR:-${INSTALL_DIR}}"
    info "Prüfe Samba-Include in [global] …"
    PYTHONPATH="${py_src}" python3 - <<'PY'
from pathlib import Path
from app.smbconf_parser import repair_smb_conf_include

if repair_smb_conf_include(Path("/etc/samba/smb.conf")):
    print("Include-Zeile in [global] ergänzt/repariert.")
PY
}

detect_shares_base_from_smb_conf() {
    local src_dir="$1"
    if [[ -n "${SIMPLE_SAMBA_SHARES_BASE:-}" ]]; then
        echo "${SIMPLE_SAMBA_SHARES_BASE}"
        return 0
    fi
    if [[ ! -f "${SMB_CONF}" ]]; then
        return 0
    fi
    PYTHONPATH="${src_dir}" python3 - <<'PY'
import sys
from pathlib import Path

from app.smbconf_parser import infer_shares_base_path, parse_all_smb_conf_shares

shares = parse_all_smb_conf_shares(Path("/etc/samba/smb.conf"))
if not shares:
    sys.exit(0)
print(infer_shares_base_path([share.path for share in shares]))
PY
}

auto_import_smb_shares() {
    local script="${INSTALL_DIR}/scripts/bootstrap-import-shares.py"
    if [[ ! -f "${script}" ]]; then
        return 0
    fi
    info "Importiere bestehende Freigaben aus smb.conf …"
    if "${INSTALL_DIR}/venv/bin/python3" "${script}"; then
        return 0
    fi
    warn "Automatischer Freigabe-Import fehlgeschlagen (optional)."
    return 0
}

_shares_base_from_config() {
    if [[ -f "${CONFIG_FILE}" ]]; then
        python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['shares_base_path'])" 2>/dev/null \
            || echo "/srv/shares"
    else
        echo "/srv/shares"
    fi
}

install_systemd_units() {
    local src="$1"
    local shares_base
    shares_base="$(_shares_base_from_config)"
    info "Installiere systemd-Units (Basis: ${shares_base}) …"
    sed "s|@SHARES_BASE@|${shares_base}|g" \
        "${src}/etc/simple-samba-ui.service" >/etc/systemd/system/simple-samba-ui.service
    sed "s|@SHARES_BASE@|${shares_base}|g" \
        "${src}/etc/simple-samba-ui-priv.service" >/etc/systemd/system/simple-samba-ui-priv.service
}

ensure_tls_certificates() {
    local tls_dir="${CONFIG_DIR}/tls"
    local cert="${tls_dir}/server.crt"
    local key="${tls_dir}/server.key"
    mkdir -p "${tls_dir}"
    if [[ ! -f "${cert}" || ! -f "${key}" ]]; then
        info "Erzeuge selbstsigniertes TLS-Zertifikat …"
        openssl req -x509 -newkey rsa:2048 -nodes \
            -keyout "${key}" -out "${cert}" -days 3650 \
            -subj "/CN=simple-samba-ui/O=Simple Samba UI" 2>/dev/null
    fi
    chown -R samba-ui:samba-ui "${tls_dir}" 2>/dev/null || true
    chmod 750 "${tls_dir}"
    chmod 640 "${key}"
    chmod 644 "${cert}"
}

ensure_https_defaults() {
    if [[ ! -f "${CONFIG_FILE}" ]]; then
        return 0
    fi
    info "HTTPS-Standard prüfen …"
    local py="${INSTALL_DIR}/venv/bin/python3"
    [[ -x "${py}" ]] || py=python3
    local migrate="${INSTALL_DIR}/scripts/migrate-https-config.py"
    [[ -f "${migrate}" ]] || migrate="${_INSTALL_COMMON_DIR}/scripts/migrate-https-config.py"
    "${py}" "${migrate}" || true
    ensure_tls_certificates
    chown samba-ui:samba-ui "${CONFIG_FILE}" 2>/dev/null || true
    chmod 600 "${CONFIG_FILE}"
}

set_permissions() {
    info "Setze Berechtigungen …"
    chown -R samba-ui:samba-ui "${INSTALL_DIR}"
    chmod 750 "${INSTALL_DIR}"
    chmod 755 "${INSTALL_DIR}/scripts/simple-samba-ui-priv-daemon.py" 2>/dev/null || true
    chmod 755 "${INSTALL_DIR}/scripts/run-app-update.py" 2>/dev/null || true
    chmod 755 "${INSTALL_DIR}/scripts/bootstrap-import-shares.py" 2>/dev/null || true
    chmod 755 "${INSTALL_DIR}/scripts/enable-tls.sh" 2>/dev/null || true
    chmod 755 "${INSTALL_DIR}/scripts/start-web.sh" 2>/dev/null || true
    chmod 755 "${INSTALL_DIR}/scripts/http-redirect-server.py" 2>/dev/null || true
    chmod 755 "${INSTALL_DIR}/scripts/migrate-https-config.py" 2>/dev/null || true
    mkdir -p "${CONFIG_DIR}" "${BACKUP_DIR}"
    chown -R samba-ui:samba-ui "${CONFIG_DIR}"
    chmod 750 "${CONFIG_DIR}"
    chmod 750 "${BACKUP_DIR}"
    if [[ -f "${CONFIG_FILE}" ]]; then
        chmod 600 "${CONFIG_FILE}"
    fi
    if [[ -f "${CONFIG_DIR}/initial-password.txt" ]]; then
        chown samba-ui:samba-ui "${CONFIG_DIR}/initial-password.txt"
        chmod 600 "${CONFIG_DIR}/initial-password.txt"
    fi
    mkdir -p /var/lib/samba-ui/apt-job /var/lib/samba-ui/app-update-job /var/lib/samba-ui/file-staging /var/lib/samba-ui/download-jobs
    chown root:samba-ui /var/lib/samba-ui/apt-job /var/lib/samba-ui/app-update-job /var/lib/samba-ui/file-staging /var/lib/samba-ui/download-jobs
    chmod 750 /var/lib/samba-ui/apt-job /var/lib/samba-ui/app-update-job /var/lib/samba-ui/download-jobs
    chmod 770 /var/lib/samba-ui/file-staging
    mkdir -p /run/simple-samba-ui
    chown root:samba-ui /run/simple-samba-ui
    chmod 750 /run/simple-samba-ui
    ensure_ui_read_access
    ensure_samba_ui_share_groups
}

wait_for_priv_socket() {
    local i
    for i in $(seq 1 20); do
        if [[ -S /run/simple-samba-ui/priv.sock ]]; then
            return 0
        fi
        sleep 0.25
    done
    warn "Privilege-Socket nicht rechtzeitig bereit."
    return 1
}

ensure_ui_read_access() {
    local base
    base="$(_shares_base_from_config)"
    if command -v setfacl &>/dev/null && id samba-ui &>/dev/null && [[ -d "${base}" ]]; then
        info "Setze Lese-ACL für samba-ui auf ${base} …"
        if ! setfacl -Rm "u:samba-ui:rx" "${base}" 2>/dev/null; then
            warn "ACL auf ${base} nicht setzbar (z. B. ZFS noacl) – nutze Gruppen-Zugriff."
        fi
    fi
}

ensure_samba_ui_share_groups() {
    if ! id samba-ui &>/dev/null; then
        return
    fi
    local py="${INSTALL_DIR}/venv/bin/python3"
    [[ -x "${py}" ]] || py=python3
    local group changed=false
    while IFS= read -r group; do
        [[ -n "${group}" ]] || continue
        if ! getent group "${group}" &>/dev/null; then
            continue
        fi
        if id -nG samba-ui | tr ' ' '\n' | grep -qx "${group}"; then
            continue
        fi
        if usermod -aG "${group}" samba-ui; then
            info "samba-ui zur Gruppe ${group} hinzugefügt (Download-Zugriff)."
            changed=true
        fi
    done < <("${py}" <<'PY'
import grp
import pwd
import sys
sys.path.insert(0, "/opt/simple-samba-ui")
from app.config import load_config
from app.samba import read_shares

cfg = load_config()
groups: set[str] = set()
for share in read_shares(cfg["samba_shares_file"]):
    if share.guest_ok:
        continue
    for user in share.valid_users:
        try:
            groups.add(grp.getgrgid(pwd.getpwnam(user).pw_gid).gr_name)
        except (KeyError, OSError):
            pass
for name in sorted(groups):
    print(name)
PY
)
    if [[ "${changed}" == "true" ]]; then
        systemctl restart simple-samba-ui 2>/dev/null || true
    fi
}

wait_for_service_active() {
    local svc="$1"
    local i
    for i in $(seq 1 30); do
        if systemctl is-active --quiet "${svc}"; then
            return 0
        fi
        sleep 0.5
    done
    return 1
}

start_services() {
    info "Starte Dienste …"
    systemctl daemon-reload
    systemctl enable simple-samba-ui-priv simple-samba-ui 2>/dev/null || true
    systemctl restart simple-samba-ui-priv
    wait_for_priv_socket || true
    systemctl restart simple-samba-ui
    wait_for_service_active simple-samba-ui || warn "simple-samba-ui startet verzögert – prüfe journalctl -u simple-samba-ui"
    systemctl enable smbd nmbd 2>/dev/null || systemctl enable smbd 2>/dev/null || true
    systemctl start smbd nmbd 2>/dev/null || systemctl start smbd 2>/dev/null || true
}

verify_installation() {
    local ok=true
    local svc
    for svc in simple-samba-ui-priv simple-samba-ui smbd; do
        if systemctl is-active --quiet "${svc}"; then
            info "${svc}: aktiv"
        else
            warn "${svc}: nicht aktiv"
            if [[ "${svc}" == "simple-samba-ui" ]]; then
                journalctl -u simple-samba-ui -n 15 --no-pager 2>/dev/null | sed 's/^/    /' || true
            fi
            ok=false
        fi
    done
    if [[ "${ok}" == true ]]; then
        info "Installation erfolgreich verifiziert."
    else
        warn "Diagnose: journalctl -u simple-samba-ui -n 50"
    fi
}

generate_bcrypt_hash() {
    local password="$1"
    "${INSTALL_DIR}/venv/bin/python3" -c "
import bcrypt
print(bcrypt.hashpw('${password}'.encode(), bcrypt.gensalt(rounds=12)).decode())
"
}

write_initial_config() {
    local admin_user="$1"
    local admin_password="$2"
    local shares_base="$3"
    local bind_host="$4"
    local bind_port="$5"
    local http_port="${6:-8080}"
    local session_secret password_hash

    session_secret="$(openssl rand -hex 32)"
    password_hash="$(generate_bcrypt_hash "${admin_password}")"
    ensure_tls_certificates

    mkdir -p "${CONFIG_DIR}"
    python3 - <<PY
import json
from pathlib import Path

cfg = {
    "bind_host": "${bind_host}",
    "bind_port": int("${bind_port}"),
    "http_port": int("${http_port}"),
    "shares_base_path": "${shares_base}",
    "samba_shares_file": "${SAMBA_SHARES_FILE}",
    "admin_username": "${admin_user}",
    "admin_password_hash": """${password_hash}""",
    "session_secret": "${session_secret}",
    "session_lifetime_hours": 8,
    "tls_enabled": True,
    "tls_cert_file": "${CONFIG_DIR}/tls/server.crt",
    "tls_key_file": "${CONFIG_DIR}/tls/server.key",
}
path = Path("${CONFIG_FILE}")
path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
PY
    chown samba-ui:samba-ui "${CONFIG_FILE}" 2>/dev/null || true
    chmod 600 "${CONFIG_FILE}"
    echo "${admin_password}" >"${CONFIG_DIR}/initial-password.txt"
    chown samba-ui:samba-ui "${CONFIG_DIR}/initial-password.txt" 2>/dev/null || true
    chmod 600 "${CONFIG_DIR}/initial-password.txt"
}
