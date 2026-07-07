"""Konfigurationsverwaltung für Simple Samba UI."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("/etc/simple-samba-ui/config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "bind_host": "127.0.0.1",
    "bind_port": 8080,
    "shares_base_path": "/srv/shares",
    "samba_shares_file": "/etc/samba/smb-shares.conf",
    "admin_username": "admin",
    "admin_password_hash": "",
    "session_secret": "",
    "session_lifetime_hours": 8,
    "github_repo": "MarcelRuh/simple-samba",
    "github_branch": "main",
    "update_check_enabled": True,
    "update_check_interval_hours": 6,
    "source_clone_dir": "/usr/local/src/simple-samba",
}


class ConfigError(Exception):
    """Fehler beim Laden oder Speichern der Konfiguration."""


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        raise ConfigError(f"Konfigurationsdatei nicht gefunden: {CONFIG_PATH}")
    try:
        with CONFIG_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Konfiguration unlesbar: {exc}") from exc

    merged = {**DEFAULT_CONFIG, **data}
    if not merged.get("session_secret"):
        raise ConfigError("session_secret fehlt in der Konfiguration")
    if not merged.get("admin_password_hash"):
        raise ConfigError("admin_password_hash fehlt in der Konfiguration")
    return merged


def save_config(data: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_PATH)


def generate_session_secret() -> str:
    return secrets.token_hex(32)
