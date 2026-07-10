"""Audit-Protokoll für Admin-Aktionen."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_LOG_PATH = Path("/var/log/simple-samba-ui/audit.log")
MAX_READ_LINES = 500

ACTION_LABELS: dict[str, str] = {
    "auth.login": "Anmeldung",
    "auth.login_failed": "Anmeldung fehlgeschlagen",
    "auth.logout": "Abmeldung",
    "auth.password_changed": "Admin-Passwort geändert",
    "share.create": "Freigabe erstellt",
    "share.update": "Freigabe bearbeitet",
    "share.delete": "Freigabe gelöscht",
    "share.import": "Freigaben importiert",
    "share.toggle": "Freigabe ein/aus",
    "user.create": "Benutzer angelegt",
    "user.password": "Benutzer-Passwort geändert",
    "user.delete": "Benutzer gelöscht",
    "file.upload": "Datei hochgeladen",
    "file.mkdir": "Ordner erstellt",
    "file.delete": "Datei/Ordner gelöscht",
    "service.reload": "Samba neu geladen",
    "service.restart": "Samba neu gestartet",
    "system.apt_update": "Paketlisten aktualisiert",
    "system.app_update": "App-Update gestartet",
    "system.reboot": "System-Neustart",
    "backup.restore": "Backup wiederhergestellt",
}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)


def _actor(user: str | None) -> str:
    if user:
        return user
    try:
        from flask import has_request_context, session

        if has_request_context():
            return str(session.get("username") or "admin")
    except Exception:
        pass
    return "system"


def audit_log(action: str, detail: str = "", *, user: str | None = None) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": _actor(user),
        "action": action,
        "detail": detail,
    }
    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
        os.chmod(AUDIT_LOG_PATH, 0o640)
    except OSError:
        pass


def read_audit_log(limit: int = MAX_READ_LINES) -> list[dict[str, Any]]:
    if not AUDIT_LOG_PATH.is_file():
        return []
    try:
        lines = AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                entries.append(data)
        except json.JSONDecodeError:
            continue
    entries.reverse()
    return entries
