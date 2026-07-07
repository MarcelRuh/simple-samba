"""Tests für Freigabe-Sicherheitsprüfungen."""

from __future__ import annotations

from app.samba import Share
from app.security_checks import share_security_warnings


def test_share_security_warnings_guest():
    shares = [Share(name="public", path="/srv/shares/public", guest_ok=True, enabled=True)]
    warnings = share_security_warnings(shares)
    assert len(warnings) == 1
    assert "Gast" in warnings[0]["message"]


def test_share_security_warnings_no_users():
    shares = [Share(name="data", path="/srv/shares/data", valid_users=[], enabled=True)]
    warnings = share_security_warnings(shares)
    assert len(warnings) == 1
    assert "keine erlaubten Benutzer" in warnings[0]["message"]


def test_share_security_warnings_ok():
    shares = [
        Share(
            name="secure",
            path="/srv/shares/secure",
            valid_users=["alice"],
            enabled=True,
        )
    ]
    assert share_security_warnings(shares) == []


def test_share_security_warnings_ignores_disabled():
    shares = [Share(name="old", path="/srv/shares/old", guest_ok=True, enabled=False)]
    assert share_security_warnings(shares) == []
