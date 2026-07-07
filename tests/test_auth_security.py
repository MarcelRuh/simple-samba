"""Tests für Auth, CSRF und sichere Redirects."""

from __future__ import annotations

import pytest

from app.auth import (
    attempt_login,
    hash_password,
    safe_redirect_target,
    verify_password,
)
from app.csrf import CSRF_SESSION_KEY


def test_hash_and_verify_password():
    hashed = hash_password("geheim123")
    assert verify_password("geheim123", hashed)
    assert not verify_password("falsch", hashed)


def test_attempt_login_success(app_config, monkeypatch):
    config_path, _ = app_config
    monkeypatch.setattr("app.config.CONFIG_PATH", config_path)
    assert attempt_login("admin", "testpass123")
    assert not attempt_login("admin", "wrong")
    assert not attempt_login("other", "testpass123")


@pytest.mark.parametrize(
    "target,expected",
    [
        ("/dashboard", "/dashboard"),
        ("//evil.example", "/"),
        ("/\\evil", "/"),
        ("https://evil.example", "/"),
        (None, "/"),
        ("", "/"),
    ],
)
def test_safe_redirect_target(target, expected):
    assert safe_redirect_target(target, "/") == expected


def _login_post(client, next_url: str = "", username: str = "admin", password: str = "testpass123"):
    query = f"/login?next={next_url}" if next_url else "/login"
    client.get(query)
    with client.session_transaction() as sess:
        token = sess[CSRF_SESSION_KEY]
    return client.post(
        query,
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def test_login_rejects_open_redirect(client):
    res = _login_post(client, next_url="//evil.example")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/")
    assert "evil" not in res.headers["Location"]


def test_login_success_redirects_to_status(client):
    res = _login_post(client, next_url="/status")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/status")


def test_login_allows_repeated_failed_attempts(client):
    for _ in range(10):
        res = _login_post(client, password="wrong")
        assert res.status_code == 200
        assert b"Ung\xc3\xbcltiger Benutzername oder Passwort" in res.data


def test_csrf_required_for_post(client):
    res = client.post("/logout", data={})
    assert res.status_code == 403


def test_csrf_token_created_on_authenticated_page(client):
    from datetime import datetime, timezone

    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["username"] = "admin"
        sess["login_at"] = datetime.now(timezone.utc).isoformat()
    client.get("/")
    with client.session_transaction() as sess:
        assert CSRF_SESSION_KEY in sess
