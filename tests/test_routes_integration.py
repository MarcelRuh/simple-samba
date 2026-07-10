"""Integrationstests für System-Routen."""

from __future__ import annotations

from app.csrf import CSRF_SESSION_KEY
from tests.test_auth_security import _login_post


def _csrf_headers(client) -> dict[str, str]:
    _login_post(client)
    client.get("/")
    with client.session_transaction() as sess:
        token = sess[CSRF_SESSION_KEY]
    return {"X-CSRF-Token": token, "Content-Type": "application/json"}


def test_system_reboot_requires_login(client):
    res = client.post("/system/updates/reboot")
    assert res.status_code == 403


def test_system_reboot_requires_csrf(client):
    _login_post(client)
    res = client.post("/system/updates/reboot")
    assert res.status_code == 403


def test_system_reboot_success(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.system.system_reboot",
        lambda: "Neustart wurde geplant.",
    )
    res = client.post("/system/updates/reboot", headers=_csrf_headers(client))
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "Neustart" in data["message"]


def test_system_reboot_priv_error(client, monkeypatch):
    from app.system import SystemUpdateError

    def _fail():
        raise SystemUpdateError("Kein Neustart erforderlich.")

    monkeypatch.setattr("app.routes.system.system_reboot", _fail)
    res = client.post("/system/updates/reboot", headers=_csrf_headers(client))
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_files_browse_requires_login(client):
    res = client.get("/api/files/browse?share=data&path=")
    assert res.status_code == 302


def test_files_browse_returns_json(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.files_routes.list_directory",
        lambda _share, _path: {
            "rel_path": "",
            "parent_rel": None,
            "entries": [{"name": "docs", "type": "dir", "size": 0, "mtime": 0}],
        },
    )
    _login_post(client)
    res = client.get("/api/files/browse?share=data&path=")
    assert res.status_code == 200
    data = res.get_json()
    assert data["entries"][0]["name"] == "docs"
