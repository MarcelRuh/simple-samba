"""Prüft GitHub auf neuere Simple-Samba-UI-Versionen."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CACHE_PATH = Path("/var/lib/samba-ui/app-update-check.json")
VERSION_RE = re.compile(r"""__version__\s*=\s*['"]([^'"]+)['"]""")
DEFAULT_REPO = "MarcelRuh/simple-samba"
DEFAULT_BRANCH = "main"
DEFAULT_INTERVAL_HOURS = 6
REQUEST_TIMEOUT = 12
USER_AGENT = "Simple-Samba-UI-UpdateCheck/1.0"


@dataclass
class AppUpdateInfo:
    current_version: str
    latest_version: str | None
    update_available: bool
    github_repo: str
    github_branch: str
    repo_url: str
    bootstrap_command: str
    manual_command: str
    check_error: str | None
    checked_at: float | None
    from_cache: bool


def parse_version(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lstrip("vV")
    parts: list[int] = []
    for segment in cleaned.split("."):
        match = re.match(r"(\d+)", segment)
        parts.append(int(match.group(1)) if match else 0)
    return tuple(parts) or (0,)


def is_newer_version(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def _settings(config: dict[str, Any]) -> tuple[str, str, bool, int]:
    repo = str(config.get("github_repo") or DEFAULT_REPO).strip("/")
    branch = str(config.get("github_branch") or DEFAULT_BRANCH).strip()
    enabled = bool(config.get("update_check_enabled", True))
    interval = int(config.get("update_check_interval_hours") or DEFAULT_INTERVAL_HOURS)
    return repo, branch, enabled, max(1, interval)


def _raw_version_url(repo: str, branch: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/app/__init__.py"


def _fetch_remote_version(repo: str, branch: str) -> str:
    url = _raw_version_url(repo, branch)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        body = response.read().decode("utf-8", errors="replace")
    match = VERSION_RE.search(body)
    if not match:
        raise ValueError("Versionsnummer in GitHub-Quellcode nicht gefunden.")
    return match.group(1)


def _load_cache() -> dict[str, Any] | None:
    if not CACHE_PATH.is_file():
        return None
    try:
        with CACHE_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(data: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(CACHE_PATH)


def _cache_valid(cache: dict[str, Any], repo: str, branch: str, max_age_seconds: float) -> bool:
    if cache.get("github_repo") != repo or cache.get("github_branch") != branch:
        return False
    checked_at = cache.get("checked_at")
    if not isinstance(checked_at, (int, float)):
        return False
    return (time.time() - float(checked_at)) < max_age_seconds


def get_app_update_info(
    config: dict[str, Any],
    current_version: str,
    *,
    force_refresh: bool = False,
) -> AppUpdateInfo:
    repo, branch, enabled, interval_hours = _settings(config)
    repo_url = f"https://github.com/{repo}"
    bootstrap_command = (
        f"curl -fsSL https://raw.githubusercontent.com/{repo}/{branch}/bootstrap.sh | sudo bash"
    )
    manual_command = "cd /usr/local/src/simple-samba && git pull && sudo bash update.sh"

    if not enabled:
        return AppUpdateInfo(
            current_version=current_version,
            latest_version=None,
            update_available=False,
            github_repo=repo,
            github_branch=branch,
            repo_url=repo_url,
            bootstrap_command=bootstrap_command,
            manual_command=manual_command,
            check_error=None,
            checked_at=None,
            from_cache=False,
        )

    max_age = interval_hours * 3600
    cache = None if force_refresh else _load_cache()
    from_cache = False
    latest_version: str | None = None
    check_error: str | None = None
    checked_at: float | None = None

    if cache and _cache_valid(cache, repo, branch, max_age):
        from_cache = True
        checked_at = float(cache["checked_at"])
        latest_version = cache.get("latest_version")
        check_error = cache.get("check_error")
    else:
        checked_at = time.time()
        try:
            latest_version = _fetch_remote_version(repo, branch)
            check_error = None
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            latest_version = cache.get("latest_version") if cache else None
            check_error = str(exc)
        _save_cache(
            {
                "checked_at": checked_at,
                "github_repo": repo,
                "github_branch": branch,
                "latest_version": latest_version,
                "check_error": check_error,
            }
        )

    update_available = bool(
        latest_version
        and not check_error
        and is_newer_version(latest_version, current_version)
    )

    return AppUpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        update_available=update_available,
        github_repo=repo,
        github_branch=branch,
        repo_url=repo_url,
        bootstrap_command=bootstrap_command,
        manual_command=manual_command,
        check_error=check_error,
        checked_at=checked_at,
        from_cache=from_cache,
    )
