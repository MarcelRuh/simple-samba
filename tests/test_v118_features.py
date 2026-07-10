"""Tests für Audit-Protokoll, ZIP-Limits und Backups."""

from __future__ import annotations

import json

import pytest

from app.audit import ACTION_LABELS, audit_log, read_audit_log
from app.backups import BackupError, list_config_backups, restore_config_backup
from app.files import FileBrowserError, validate_folder_download_manifest
from tests.test_auth_security import _login_post


def test_validate_folder_download_manifest_rejects_too_many_files():
    manifest = {"total_files": 10_000, "total_size": 1000, "files": []}
    with pytest.raises(FileBrowserError, match="zu viele Dateien"):
        validate_folder_download_manifest(manifest, {"max_folder_download_files": 5000})


def test_validate_folder_download_manifest_rejects_too_large():
    manifest = {"total_files": 10, "total_size": 30 * 1024**3, "files": []}
    with pytest.raises(FileBrowserError, match="zu groß"):
        validate_folder_download_manifest(
            manifest,
            {"max_folder_download_bytes": 20 * 1024**3},
        )


def test_validate_folder_download_manifest_accepts_within_limits():
    manifest = {"total_files": 100, "total_size": 1024, "files": []}
    validate_folder_download_manifest(
        manifest,
        {
            "max_folder_download_files": 5000,
            "max_folder_download_bytes": 20 * 1024**3,
        },
    )


def test_audit_log_writes_and_reads(tmp_path, monkeypatch):
    log_path = tmp_path / "audit.log"
    monkeypatch.setattr("app.audit.AUDIT_LOG_PATH", log_path)

    audit_log("share.create", "data", user="admin")
    audit_log("auth.login", "success", user="admin")

    entries = read_audit_log()
    assert len(entries) == 2
    assert entries[0]["action"] == "auth.login"
    assert entries[1]["action"] == "share.create"
    assert entries[1]["detail"] == "data"


def test_action_labels_cover_core_actions():
    for action in (
        "auth.login",
        "share.create",
        "file.upload",
        "backup.restore",
        "system.reboot",
    ):
        assert action in ACTION_LABELS


def test_list_config_backups_parses_response(monkeypatch):
    payload = json.dumps(
        {
            "backups": [
                {"name": "smb-shares.conf.20260101.bak", "type": "shares", "size": 1024, "mtime": 1}
            ]
        }
    )

    monkeypatch.setattr("app.backups._priv_request", lambda *_a, **_k: (True, payload))
    backups = list_config_backups()
    assert len(backups) == 1
    assert backups[0]["name"] == "smb-shares.conf.20260101.bak"


def test_list_config_backups_priv_error(monkeypatch):
    monkeypatch.setattr("app.backups._priv_request", lambda *_a, **_k: (False, "fehler"))
    with pytest.raises(BackupError, match="fehler"):
        list_config_backups()


def test_restore_config_backup_success(monkeypatch):
    monkeypatch.setattr(
        "app.backups._priv_request",
        lambda cmd, **_k: (True, "OK") if cmd == "backup-restore" else (False, ""),
    )
    assert restore_config_backup("smb-shares.conf.test.bak") == "OK"


def test_audit_log_page_requires_login(client):
    res = client.get("/protokoll")
    assert res.status_code == 302


def test_audit_log_page_renders(client, monkeypatch, tmp_path):
    log_path = tmp_path / "audit.log"
    log_path.write_text(
        json.dumps({"ts": "2026-01-01T12:00:00+00:00", "user": "admin", "action": "auth.login", "detail": "success"})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.audit.AUDIT_LOG_PATH", log_path)
    _login_post(client)
    res = client.get("/protokoll")
    assert res.status_code == 200
    assert b"Anmeldung" in res.data


def test_backups_page_requires_login(client):
    res = client.get("/backups")
    assert res.status_code == 302


def test_backups_page_lists_backups(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.admin_tools.list_config_backups",
        lambda: [
            {
                "name": "smb-shares.conf.test.bak",
                "type": "shares",
                "size": 2048,
                "mtime": 1700000000,
            }
        ],
    )
    _login_post(client)
    res = client.get("/backups")
    assert res.status_code == 200
    assert b"smb-shares.conf.test.bak" in res.data


def test_download_manifest_calls_validation(monkeypatch):
    manifest = {"name": "docs", "files": [], "total_files": 0, "total_size": 0}
    calls: list[dict] = []

    def _capture(m, c):
        calls.append({"manifest": m, "config": c})

    monkeypatch.setattr(
        "app.files.read_shares",
        lambda _path: [__import__("app.samba", fromlist=["Share"]).Share(name="data", path="/srv/data")],
    )
    monkeypatch.setattr(
        "app.files.load_config",
        lambda: {
            "samba_shares_file": "/tmp/x",
            "shares_base_path": "/srv",
            "max_folder_download_files": 5000,
        },
    )
    monkeypatch.setattr("app.files._priv_request", lambda *_a, **_k: (True, json.dumps(manifest)))
    monkeypatch.setattr("app.files.validate_folder_download_manifest", _capture)

    from app.files import download_manifest

    result = download_manifest("data", "docs")
    assert result == manifest
    assert len(calls) == 1
