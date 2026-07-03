#!/usr/bin/env python3
"""Detached App-Self-Update von GitHub (root). Überlebt Neustart von simple-samba-ui-priv."""

from __future__ import annotations

import grp
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

JOB_DIR = Path("/var/lib/samba-ui/app-update-job")
STATUS_FILE = JOB_DIR / "status.json"
LOG_FILE = JOB_DIR / "output.log"
DEFAULT_CLONE_DIR = Path("/usr/local/src/simple-samba")
DEFAULT_REPO = "MarcelRuh/simple-samba"
DEFAULT_BRANCH = "main"
GIT = "/usr/bin/git"
BASH = "/bin/bash"
SAMBA_UI_GROUP = "samba-ui"

PHASE_LABELS = {
    "start": "Wird gestartet …",
    "clone": "Quellcode von GitHub laden",
    "deploy": "App installieren",
    "done": "Abgeschlossen",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chown_job_files() -> None:
    try:
        gid = grp.getgrnam(SAMBA_UI_GROUP).gr_gid
    except KeyError:
        return
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    os.chown(JOB_DIR, 0, gid)
    os.chmod(JOB_DIR, 0o750)
    for path in (STATUS_FILE, LOG_FILE):
        if path.is_file():
            os.chown(path, 0, gid)
            os.chmod(path, 0o660)


def _log(text: str) -> None:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(text.rstrip("\n") + "\n")
    _chown_job_files()


def _write_status(*, status: str, phase: str, success: bool | None = None,
                  started_at: str | None = None, finished_at: str | None = None,
                  new_version: str | None = None) -> None:
    payload = {
        "status": status,
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "success": success,
        "started_at": started_at,
        "finished_at": finished_at,
        "new_version": new_version,
    }
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _chown_job_files()


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _read_local_version(clone_dir: Path) -> str | None:
    init_py = clone_dir / "app" / "__init__.py"
    if not init_py.is_file():
        return None
    for line in init_py.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main() -> int:
    clone_dir = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CLONE_DIR)
    repo = (sys.argv[2] if len(sys.argv) > 2 else DEFAULT_REPO).strip("/")
    branch = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_BRANCH
    repo_url = f"https://github.com/{repo}.git"

    started = _iso_now()
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("", encoding="utf-8")
    _write_status(status="running", phase="start", started_at=started)
    _log(f"Simple Samba UI – Update von GitHub ({repo}@{branch})")
    _log(f"Zielverzeichnis: {clone_dir}")

    if not Path(GIT).is_file():
        _log("Fehler: git ist nicht installiert.")
        _write_status(
            status="failed", phase="done", success=False,
            started_at=started, finished_at=_iso_now(),
        )
        return 1

    _write_status(status="running", phase="clone", started_at=started)
    clone_dir.parent.mkdir(parents=True, exist_ok=True)

    if not (clone_dir / ".git").is_dir():
        _log(f"Klone Repository nach {clone_dir} …")
        result = _run([GIT, "clone", "--depth", "1", "--branch", branch, repo_url, str(clone_dir)])
    else:
        _log(f"Aktualisiere vorhandenes Repository in {clone_dir} …")
        fetch = _run([GIT, "-C", str(clone_dir), "fetch", "--depth", "1", "origin", branch])
        _log(fetch.stdout)
        _log(fetch.stderr)
        if fetch.returncode != 0:
            _write_status(status="failed", phase="done", success=False, started_at=started, finished_at=_iso_now())
            return fetch.returncode
        checkout = _run([GIT, "-C", str(clone_dir), "checkout", branch])
        reset = _run([GIT, "-C", str(clone_dir), "reset", "--hard", f"origin/{branch}"])
        result = reset if reset.returncode != 0 else checkout

    _log(result.stdout)
    _log(result.stderr)
    if result.returncode != 0:
        _write_status(status="failed", phase="done", success=False, started_at=started, finished_at=_iso_now())
        return result.returncode

    update_sh = clone_dir / "update.sh"
    if not update_sh.is_file():
        _log(f"Fehler: {update_sh} nicht gefunden.")
        _write_status(status="failed", phase="done", success=False, started_at=started, finished_at=_iso_now())
        return 1

    new_version = _read_local_version(clone_dir)
    if new_version:
        _log(f"Neue Version: v{new_version}")

    _write_status(status="running", phase="deploy", started_at=started, new_version=new_version)
    _log(f"Starte {update_sh} …")
    deploy = _run([BASH, str(update_sh)], cwd=clone_dir, timeout=900)
    _log(deploy.stdout)
    _log(deploy.stderr)

    finished = _iso_now()
    if deploy.returncode != 0:
        _write_status(
            status="failed", phase="done", success=False,
            started_at=started, finished_at=finished, new_version=new_version,
        )
        return deploy.returncode

    _log("App-Update abgeschlossen.")
    _write_status(
        status="done", phase="done", success=True,
        started_at=started, finished_at=finished, new_version=new_version,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _log(f"Interner Fehler: {exc}")
        _write_status(
            status="failed",
            phase="done",
            success=False,
            started_at=_iso_now(),
            finished_at=_iso_now(),
        )
        raise
