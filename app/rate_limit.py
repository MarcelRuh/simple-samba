"""Login-Rate-Limiting nach IP-Adresse."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

ATTEMPTS_PATH = Path("/etc/simple-samba-ui/login_attempts.json")
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60


def _load() -> dict:
    if not ATTEMPTS_PATH.is_file():
        return {}
    try:
        with ATTEMPTS_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    ATTEMPTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ATTEMPTS_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    tmp.replace(ATTEMPTS_PATH)
    try:
        import os

        os.chmod(ATTEMPTS_PATH, 0o600)
    except OSError:
        pass


def is_login_locked(ip: str) -> tuple[bool, int]:
    """Gibt (gesperrt, verbleibende Sekunden) zurück."""
    entry = _load().get(ip)
    if not entry:
        return False, 0
    locked_until = float(entry.get("locked_until", 0))
    now = time.time()
    if locked_until > now:
        return True, int(locked_until - now)
    return False, 0


def record_failed_login(ip: str) -> None:
    data = _load()
    entry = data.get(ip, {"count": 0, "locked_until": 0})
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last_failed"] = datetime.now(timezone.utc).isoformat()
    if entry["count"] >= MAX_ATTEMPTS:
        entry["locked_until"] = time.time() + LOCKOUT_SECONDS
        entry["count"] = 0
    data[ip] = entry
    _save(data)


def clear_login_attempts(ip: str) -> None:
    data = _load()
    if ip in data:
        del data[ip]
        _save(data)
