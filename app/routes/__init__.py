"""HTTP-Routen – nach Modulen aufgeteilt, Endpoints bleiben unverändert."""

from __future__ import annotations

from flask import Flask


def register_routes(app: Flask) -> None:
    from app.routes import admin_tools, auth, dashboard, files_routes, service, shares, system, users

    auth.register(app)
    dashboard.register(app)
    admin_tools.register(app)
    shares.register(app)
    users.register(app)
    files_routes.register(app)
    service.register(app)
    system.register(app)
