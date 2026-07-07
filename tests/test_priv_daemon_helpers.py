"""Tests für Hilfsfunktionen im Privilege-Daemon."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

DAEMON_PATH = Path(__file__).resolve().parents[1] / "scripts" / "simple-samba-ui-priv-daemon.py"


def _load_daemon_module():
    spec = importlib.util.spec_from_file_location("priv_daemon", DAEMON_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["priv_daemon"] = module
    spec.loader.exec_module(module)
    return module


def test_app_update_job_lock_defined():
    daemon = _load_daemon_module()
    lock = getattr(daemon, "_app_update_job_lock", None)
    assert lock is not None
    assert hasattr(lock, "acquire")


def test_validate_browser_path_rejects_symlink(tmp_path, monkeypatch):
    daemon = _load_daemon_module()
    base = tmp_path / "shares"
    share = base / "data"
    share.mkdir(parents=True)
    secret = tmp_path / "secret"
    secret.mkdir()
    (share / "link").symlink_to(secret)

    monkeypatch.setattr(daemon, "get_shares_base", lambda: base)
    monkeypatch.setattr(daemon, "_get_enabled_share_paths", lambda: [share.resolve()])

    with pytest.raises(ValueError, match="Symbolische Links"):
        daemon.validate_browser_path(str(share / "link"))


def test_cmd_system_reboot_requires_flag(monkeypatch):
    daemon = _load_daemon_module()
    monkeypatch.setattr(daemon, "_reboot_required", lambda: False)
    ok, msg = daemon.cmd_system_reboot()
    assert not ok
    assert "Kein Neustart" in msg


def test_cleanup_stale_staging_removes_old_files(tmp_path, monkeypatch):
    daemon = _load_daemon_module()
    staging = tmp_path / "file-staging"
    jobs = tmp_path / "download-jobs"
    staging.mkdir()
    jobs.mkdir()

    old_file = staging / "upload-old.bin"
    old_file.write_bytes(b"x" * 10)
    old_ts = 1_000_000_000
    import os

    os.utime(old_file, (old_ts, old_ts))

    monkeypatch.setattr(daemon, "FILE_STAGING_DIR", staging)
    monkeypatch.setattr(daemon, "DOWNLOAD_JOBS_DIR", jobs)
    monkeypatch.setattr(daemon, "STAGING_MAX_AGE_SECONDS", 3600)
    monkeypatch.setattr(daemon, "_ensure_file_staging_dir", lambda: None)

    removed_staging, removed_jobs = daemon.cleanup_stale_staging(max_age_seconds=60)
    assert removed_staging == 1
    assert not old_file.exists()
    assert removed_jobs == 0
