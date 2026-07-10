"""Konfigurations-Backups auflisten und wiederherstellen."""

from __future__ import annotations

import json
from typing import Any

from app.samba import SambaError, _priv_request


class BackupError(Exception):
    """Fehler bei Backup-Operationen."""


def list_config_backups() -> list[dict[str, Any]]:
    ok, output = _priv_request("backup-list", timeout=30)
    if not ok:
        raise BackupError(output or "Backups konnten nicht gelesen werden.")
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise BackupError("Ungültige Antwort vom Server.") from exc
    return list(data.get("backups") or [])


def restore_config_backup(name: str) -> str:
    ok, output = _priv_request("backup-restore", arg=name, timeout=120)
    if not ok:
        raise BackupError(output or "Wiederherstellung fehlgeschlagen.")
    return output.strip() or "Backup wiederhergestellt."
