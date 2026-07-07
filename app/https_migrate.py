"""HTTPS-Standard und Migration bestehender Konfigurationen."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_HTTPS_PORT = 8443
DEFAULT_HTTP_PORT = 8080
DEFAULT_CONFIG_PATH = Path("/etc/simple-samba-ui/config.json")


def migrate(path: Path | None = None) -> bool:
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.is_file():
        return False
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    changed = False

    if not cfg.get("tls_enabled"):
        cfg["tls_enabled"] = True
        changed = True

    cfg.setdefault("tls_cert_file", "/etc/simple-samba-ui/tls/server.crt")
    cfg.setdefault("tls_key_file", "/etc/simple-samba-ui/tls/server.key")

    bind_port = int(cfg.get("bind_port", DEFAULT_HTTP_PORT))
    http_port = int(cfg.get("http_port", 0) or 0)

    if http_port <= 0:
        cfg["http_port"] = DEFAULT_HTTP_PORT
        http_port = DEFAULT_HTTP_PORT
        changed = True

    if bind_port == http_port:
        cfg["bind_port"] = DEFAULT_HTTPS_PORT
        changed = True

    if changed:
        cfg_path.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return changed
