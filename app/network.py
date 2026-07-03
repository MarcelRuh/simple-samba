"""Netzwerk-Hilfen für Anzeige und Konfiguration."""

from __future__ import annotations

import socket


def detect_primary_ipv4() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("1.1.1.1", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def resolve_access_host(bind_host: str) -> str:
    if bind_host in ("0.0.0.0", "::", "::0"):
        return detect_primary_ipv4()
    return bind_host
