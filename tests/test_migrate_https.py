"""Tests für HTTPS-Migration."""

from __future__ import annotations

import json
from pathlib import Path

from app.https_migrate import migrate


def test_migrate_enables_tls_and_splits_ports(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"bind_host": "0.0.0.0", "bind_port": 8080, "tls_enabled": False}),
        encoding="utf-8",
    )
    assert migrate(cfg_path) is True
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["tls_enabled"] is True
    assert data["bind_port"] == 8443
    assert data["http_port"] == 8080


def test_migrate_idempotent_when_already_https(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "bind_port": 8443,
                "http_port": 8080,
                "tls_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    assert migrate(cfg_path) is False
