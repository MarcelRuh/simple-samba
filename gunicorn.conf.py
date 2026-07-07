"""Gunicorn-Konfiguration – liest Bind-Adresse und TLS aus config.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_PATH = Path("/etc/simple-samba-ui/config.json")

_DEFAULT = {
    "bind_host": "127.0.0.1",
    "bind_port": 8443,
    "http_port": 8080,
    "tls_enabled": True,
    "tls_cert_file": "/etc/simple-samba-ui/tls/server.crt",
    "tls_key_file": "/etc/simple-samba-ui/tls/server.key",
}


def _load() -> dict:
    if not CONFIG_PATH.is_file():
        return dict(_DEFAULT)
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return {**_DEFAULT, **json.load(fh)}


_cfg = _load()

bind = f"{_cfg.get('bind_host', '127.0.0.1')}:{_cfg.get('bind_port', 8443)}"
workers = 2
threads = 2
timeout = 120
user = "samba-ui"
group = "samba-ui"
chdir = "/opt/simple-samba-ui"
wsgi_app = "wsgi:app"
accesslog = "-"
errorlog = "-"
loglevel = "info"
capture_output = True

forwarded_allow_ips = "127.0.0.1"
proxy_allow_ips = "127.0.0.1"

if not _cfg.get("tls_enabled"):
    print(
        "TLS ist deaktiviert – Simple Samba UI erwartet HTTPS. "
        "Bitte scripts/migrate-https-config.py ausführen.",
        file=sys.stderr,
    )
    sys.exit(1)

certfile = str(_cfg.get("tls_cert_file") or _DEFAULT["tls_cert_file"])
keyfile = str(_cfg.get("tls_key_file") or _DEFAULT["tls_key_file"])
if not Path(certfile).is_file() or not Path(keyfile).is_file():
    print(
        f"TLS-Zertifikat fehlt ({certfile}). "
        "Bitte update.sh oder scripts/enable-tls.sh ausführen.",
        file=sys.stderr,
    )
    sys.exit(1)
