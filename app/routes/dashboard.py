"""Dashboard."""

from __future__ import annotations

from flask import Flask, flash, render_template

from app.auth import login_required
from app.config import load_config
from app.samba import SambaError, read_shares, service_status
from app.system import format_bytes, format_uptime, get_overview_safe


def register(app: Flask) -> None:
    @app.route("/")
    @login_required
    def index():
        config = load_config()
        overview, overview_error = get_overview_safe()
        try:
            shares = read_shares(config["samba_shares_file"])
            status = service_status()
        except SambaError as exc:
            flash(str(exc), "error")
            shares = []
            status = {"active": "unknown", "is_running": False, "output": ""}
        return render_template(
            "index.html",
            shares=shares,
            status=status,
            config=config,
            overview=overview,
            overview_error=overview_error,
            format_bytes=format_bytes,
            format_uptime=format_uptime,
        )
