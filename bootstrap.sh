#!/bin/bash
# Simple Samba UI – One-Liner-Installation
#
#   wget -qO- https://raw.githubusercontent.com/MarcelRuh/simple-samba/main/bootstrap.sh | bash
#
# Optional (nicht-interaktiv):
#   SIMPLE_SAMBA_BIND_PORT=8080 \
#     wget -qO- https://raw.githubusercontent.com/MarcelRuh/simple-samba/main/bootstrap.sh | bash
set -euo pipefail

REPO_URL="${SIMPLE_SAMBA_REPO:-https://github.com/MarcelRuh/simple-samba.git}"
CLONE_DIR="${SIMPLE_SAMBA_CLONE_DIR:-/usr/local/src/simple-samba}"
BRANCH="${SIMPLE_SAMBA_BRANCH:-main}"
RAW_BOOTSTRAP="https://raw.githubusercontent.com/MarcelRuh/simple-samba/main/bootstrap.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}▸${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
error() { echo -e "${RED}✖${NC} $*" >&2; }

if [[ "${EUID}" -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
        warn "Root erforderlich – starte mit sudo …"
        exec sudo -E env \
            SIMPLE_SAMBA_REPO="${SIMPLE_SAMBA_REPO:-}" \
            SIMPLE_SAMBA_CLONE_DIR="${SIMPLE_SAMBA_CLONE_DIR:-}" \
            SIMPLE_SAMBA_BRANCH="${SIMPLE_SAMBA_BRANCH:-}" \
            SIMPLE_SAMBA_SHARES_BASE="${SIMPLE_SAMBA_SHARES_BASE:-}" \
            SIMPLE_SAMBA_BIND_HOST="${SIMPLE_SAMBA_BIND_HOST:-}" \
            SIMPLE_SAMBA_BIND_PORT="${SIMPLE_SAMBA_BIND_PORT:-}" \
            SIMPLE_SAMBA_NONINTERACTIVE="${SIMPLE_SAMBA_NONINTERACTIVE:-}" \
            bash -s "$@" <<'BOOTSTRAP_INLINE'
set -euo pipefail
if command -v wget >/dev/null 2>&1; then
  exec bash < <(wget -qO- 'https://raw.githubusercontent.com/MarcelRuh/simple-samba/main/bootstrap.sh')
else
  echo "wget erforderlich." >&2
  exit 1
fi
BOOTSTRAP_INLINE
    fi
    error "Root erforderlich. Bitte als root ausführen:"
    error "  su -"
    error "  wget -qO- ${RAW_BOOTSTRAP} | bash"
    exit 1
fi

ensure_apt_pkg() {
    local pkg="$1"
    if dpkg -s "${pkg}" &>/dev/null 2>&1; then
        return 0
    fi
    info "Installiere ${pkg} …"
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${pkg}"
}

ensure_bootstrap_tools() {
    if ! command -v apt-get >/dev/null 2>&1; then
        error "apt-get nicht gefunden – nur Debian/Ubuntu werden unterstützt."
        exit 1
    fi
    info "Prüfe Basiswerkzeuge (wget, git, sudo) …"
    apt-get update -qq
    ensure_apt_pkg ca-certificates
    ensure_apt_pkg wget
    ensure_apt_pkg git
    ensure_apt_pkg sudo
}

echo ""
echo "========================================"
echo "  Simple Samba UI – Bootstrap"
echo "========================================"
echo ""

ensure_bootstrap_tools

if [[ -d "${CLONE_DIR}/.git" ]]; then
    info "Aktualisiere Quellcode in ${CLONE_DIR} …"
    git -C "${CLONE_DIR}" fetch --depth 1 origin "${BRANCH}"
    git -C "${CLONE_DIR}" checkout "${BRANCH}"
    git -C "${CLONE_DIR}" reset --hard "origin/${BRANCH}"
else
    info "Klone Repository nach ${CLONE_DIR} …"
    mkdir -p "$(dirname "${CLONE_DIR}")"
    git clone --depth 1 --branch "${BRANCH}" "${REPO_URL}" "${CLONE_DIR}"
fi

export SIMPLE_SAMBA_NONINTERACTIVE="${SIMPLE_SAMBA_NONINTERACTIVE:-1}"
# Ohne SIMPLE_SAMBA_BIND_HOST: Install nutzt automatisch die LAN-IP
exec bash "${CLONE_DIR}/install.sh"
