#!/bin/bash
# Simple Samba UI – Deinstallation (als root)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/install-common.sh
source "${SCRIPT_DIR}/scripts/install-common.sh"

require_root

warn "Simple Samba UI wird deinstalliert."
read -rp "Fortfahren? (ja/nein) [nein]: " confirm
[[ "${confirm:-nein}" == "ja" ]] || exit 0

systemctl stop simple-samba-ui 2>/dev/null || true
systemctl disable simple-samba-ui 2>/dev/null || true
systemctl stop simple-samba-ui-priv 2>/dev/null || true
systemctl disable simple-samba-ui-priv 2>/dev/null || true
rm -f /etc/systemd/system/simple-samba-ui.service
rm -f /etc/systemd/system/simple-samba-ui-priv.service
systemctl daemon-reload

rm -rf "${INSTALL_DIR}"
info "App unter ${INSTALL_DIR} entfernt."

read -rp "Konfiguration ${CONFIG_DIR} löschen? (ja/nein) [nein]: " delcfg
if [[ "${delcfg:-nein}" == "ja" ]]; then
    rm -rf "${CONFIG_DIR}"
    info "Konfiguration entfernt."
fi

info "Deinstallation abgeschlossen. Samba-Freigaben (${SAMBA_SHARES_FILE}) bleiben erhalten."
