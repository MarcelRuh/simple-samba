"""Gunicorn-Konfiguration – liest Bind-Adresse aus config.json."""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path("/etc/simple-samba-ui/config.json")

def _load():
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)

_cfg = _load()

bind = f"{_cfg.get('bind_host', '127.0.0.1')}:{_cfg.get('bind_port', 8080)}"
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

# Sicherheit: nur intern
forwarded_allow_ips = "127.0.0.1"
proxy_allow_ips = "127.0.0.1"
