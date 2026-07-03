"""System-Updates und Übersicht über den Privilege-Daemon."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.samba import SambaError, _priv_request

APT_TIMEOUT_UPDATE = 660


class SystemUpdateError(Exception):
    """Fehler bei apt-Operationen."""


PKG_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+_.:-]*$", re.IGNORECASE)


@dataclass
class SystemOverview:
    disk_path: str
    disk_total: int
    disk_used: int
    disk_free: int
    disk_percent: float
    disk_error: str
    reboot_required: bool
    reboot_reason: str
    uptime_seconds: int
    upgradable_count: int


def _run_priv(command: str, timeout: int = 120) -> str:
    ok, output = _priv_request(command, timeout=timeout)
    if not ok:
        raise SystemUpdateError(output or f"{command} fehlgeschlagen.")
    return output.strip()


def _run_priv_json(command: str, timeout: int = 120) -> dict:
    raw = _run_priv(command, timeout=timeout)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError as exc:
        raise SystemUpdateError(f"Ungültige Antwort von {command}.") from exc


def parse_upgradable_output(output: str) -> list[str]:
    packages: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("Listing", "WARNING", "OK:", "Paketlisten")):
            continue
        if "aktualisierbare Paket" in line or line.startswith("System ist"):
            continue
        if line.startswith("•"):
            line = line.lstrip("•").strip()
        if "/" in line:
            line = line.split("/", 1)[0].strip()
        if PKG_NAME_RE.match(line) and line not in packages:
            packages.append(line)
    return packages


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024
        if size < 1024:
            return f"{size:.1f} {unit}"
    return f"{size:.1f} PB"


def format_uptime(seconds: int) -> str:
    days, rem = divmod(max(0, seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} T.")
    if hours:
        parts.append(f"{hours} Std.")
    if minutes or not parts:
        parts.append(f"{minutes} Min.")
    return " ".join(parts)


def apt_update() -> str:
    return _run_priv("apt-update", APT_TIMEOUT_UPDATE)


def apt_list_upgradable() -> tuple[list[str], str]:
    output = _run_priv("apt-upgradable", APT_TIMEOUT_UPDATE)
    return parse_upgradable_output(output), output


def apt_start_install_job() -> None:
    _run_priv("apt-upgrade-start", timeout=30)


def apt_job_status() -> dict:
    return _run_priv_json("apt-job-status", timeout=30)


def app_update_start() -> None:
    _run_priv("app-update-start", timeout=30)


def app_update_job_status() -> dict:
    return _run_priv_json("app-update-status", timeout=30)


def get_system_overview() -> SystemOverview:
    raw = _run_priv_json("system-overview", timeout=30)
    packages, _ = check_upgradable_safe()
    return SystemOverview(
        disk_path=str(raw.get("disk_path", "")),
        disk_total=int(raw.get("disk_total", 0)),
        disk_used=int(raw.get("disk_used", 0)),
        disk_free=int(raw.get("disk_free", 0)),
        disk_percent=float(raw.get("disk_percent", 0)),
        disk_error=str(raw.get("disk_error", "")),
        reboot_required=bool(raw.get("reboot_required")),
        reboot_reason=str(raw.get("reboot_reason", "")),
        uptime_seconds=int(raw.get("uptime_seconds", 0)),
        upgradable_count=len(packages),
    )


def check_upgradable_safe() -> tuple[list[str], str | None]:
    try:
        packages, output = apt_list_upgradable()
        return packages, output
    except (SystemUpdateError, SambaError) as exc:
        return [], str(exc)


def get_overview_safe() -> tuple[SystemOverview | None, str | None]:
    try:
        return get_system_overview(), None
    except (SystemUpdateError, SambaError) as exc:
        return None, str(exc)
