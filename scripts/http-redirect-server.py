#!/usr/bin/env python3
"""HTTP → HTTPS Redirect (301) für Simple Samba UI."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONFIG_PATH = Path("/etc/simple-samba-ui/config.json")


def load_redirect_config() -> tuple[str, int, int]:
    if not CONFIG_PATH.is_file():
        raise SystemExit(f"Konfiguration nicht gefunden: {CONFIG_PATH}")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not cfg.get("tls_enabled"):
        raise SystemExit("HTTP-Redirect nur bei aktiviertem TLS.")
    host = str(cfg.get("bind_host", "0.0.0.0"))
    http_port = int(cfg.get("http_port", 0) or 0)
    https_port = int(cfg.get("bind_port", 8443))
    if http_port <= 0:
        raise SystemExit("http_port nicht konfiguriert.")
    if http_port == https_port:
        raise SystemExit("http_port und bind_port dürfen nicht identisch sein.")
    return host, http_port, https_port


class RedirectHandler(BaseHTTPRequestHandler):
    https_port: int = 8443

    def _redirect(self) -> None:
        host_header = (self.headers.get("Host") or "").strip()
        hostname = host_header.split(":", 1)[0] if host_header else "localhost"
        port = self.https_port
        if port == 443:
            location = f"https://{hostname}{self.path}"
        else:
            location = f"https://{hostname}:{port}{self.path}"
        if self.command != "HEAD":
            body = (
                f"HTTPS erforderlich. Weiterleitung nach {location}\n"
            ).encode("utf-8")
        else:
            body = b""
        self.send_response(301, "Moved Permanently")
        self.send_header("Location", location)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        if body:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:
        self._redirect()

    def do_HEAD(self) -> None:
        self._redirect()

    def do_POST(self) -> None:
        self._redirect()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"http-redirect: {self.address_string()} - {fmt % args}\n")


def main() -> None:
    host, http_port, https_port = load_redirect_config()
    RedirectHandler.https_port = https_port
    bind = host if host not in ("", "0.0.0.0", "::") else ""
    server = ThreadingHTTPServer((bind, http_port), RedirectHandler)
    sys.stderr.write(
        f"http-redirect: lauscht auf {host or '*'}:{http_port} → https://*:{https_port}/\n"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
