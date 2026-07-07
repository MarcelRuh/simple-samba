"""Gemeinsame Test-Fixtures."""

from __future__ import annotations

import json

import bcrypt
import pytest

from app.config import CONFIG_PATH


@pytest.fixture
def app_config(tmp_path):
    config_path = tmp_path / "config.json"
    password_hash = bcrypt.hashpw(b"testpass123", bcrypt.gensalt(rounds=12)).decode()
    shares_file = tmp_path / "smb-shares.conf"
    shares_file.write_text("# test\n", encoding="utf-8")
    data = {
        "bind_host": "127.0.0.1",
        "bind_port": 8080,
        "shares_base_path": str(tmp_path / "shares"),
        "samba_shares_file": str(shares_file),
        "admin_username": "admin",
        "admin_password_hash": password_hash,
        "session_secret": "a" * 64,
        "session_lifetime_hours": 8,
        "github_repo": "MarcelRuh/simple-samba",
        "github_branch": "main",
        "update_check_enabled": False,
        "update_check_interval_hours": 6,
        "source_clone_dir": str(tmp_path / "clone"),
    }
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return config_path, data


@pytest.fixture
def app(app_config, monkeypatch):
    config_path, _data = app_config
    monkeypatch.setattr("app.config.CONFIG_PATH", config_path)

    from app.app import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
