"""Tests für TLS-Hilfen."""

from __future__ import annotations

from app.tls import is_tls_enabled, public_url, public_scheme


def test_public_scheme():
    assert public_scheme({"tls_enabled": False}) == "http"
    assert public_scheme({"tls_enabled": True}) == "https"


def test_public_url_with_port():
    cfg = {"bind_port": 8080, "tls_enabled": False}
    assert public_url(cfg, "192.168.1.10") == "http://192.168.1.10:8080/"


def test_public_url_https():
    cfg = {"bind_port": 8443, "tls_enabled": True}
    assert public_url(cfg, "10.0.0.5") == "https://10.0.0.5:8443/"


def test_is_tls_enabled():
    assert not is_tls_enabled({})
    assert is_tls_enabled({"tls_enabled": True})
