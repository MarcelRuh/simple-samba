"""TLS / HTTPS-Hilfen für die Web-UI."""

from __future__ import annotations

from typing import Any

DEFAULT_TLS_CERT = "/etc/simple-samba-ui/tls/server.crt"
DEFAULT_TLS_KEY = "/etc/simple-samba-ui/tls/server.key"


def is_tls_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("tls_enabled"))


def tls_cert_paths(config: dict[str, Any]) -> tuple[str, str]:
    cert = str(config.get("tls_cert_file") or DEFAULT_TLS_CERT)
    key = str(config.get("tls_key_file") or DEFAULT_TLS_KEY)
    return cert, key


def tls_files_present(config: dict[str, Any]) -> bool:
    from pathlib import Path

    cert, key = tls_cert_paths(config)
    return Path(cert).is_file() and Path(key).is_file()


def public_scheme(config: dict[str, Any]) -> str:
    return "https" if is_tls_enabled(config) else "http"


def public_url(config: dict[str, Any], access_host: str) -> str:
    port = int(config.get("bind_port", 8080))
    scheme = public_scheme(config)
    host = access_host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = 443 if scheme == "https" else 80
    if port == default_port:
        return f"{scheme}://{host}/"
    return f"{scheme}://{host}:{port}/"
