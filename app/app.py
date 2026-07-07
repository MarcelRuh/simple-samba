"""Flask-Anwendung – Simple Samba UI."""

from __future__ import annotations

from flask import Flask, render_template, request

from app.auth import configure_session, is_authenticated
from app.config import DEFAULT_MAX_UPLOAD_BYTES, ConfigError, load_config
from app.csrf import get_csrf_token, validate_csrf_token
from app.app_updates import get_app_update_info
from app.network import resolve_access_host
from app.routes import register_routes


def create_app() -> Flask:
    app = Flask(__name__)
    try:
        cfg = load_config()
        max_upload = int(cfg.get("max_upload_bytes", DEFAULT_MAX_UPLOAD_BYTES))
    except (ConfigError, TypeError, ValueError):
        max_upload = DEFAULT_MAX_UPLOAD_BYTES
    app.config["MAX_CONTENT_LENGTH"] = max_upload
    configure_session(app)

    @app.before_request
    def _check_csrf() -> None:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return
        if request.endpoint == "static":
            return
        validate_csrf_token()

    @app.after_request
    def _security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
        )
        return response

    @app.context_processor
    def inject_globals():
        from app import __version__
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
        access_host = resolve_access_host(str(cfg.get("bind_host", "0.0.0.0"))) if cfg else "127.0.0.1"
        app_update = None
        if is_authenticated():
            try:
                app_update = get_app_update_info(cfg, __version__)
            except Exception:
                app_update = None
        return {
            "app_name": "Simple Samba UI",
            "app_version": __version__,
            "config": cfg,
            "access_host": access_host,
            "csrf_token": get_csrf_token,
            "app_update": app_update,
        }

    register_routes(app)

    @app.errorhandler(403)
    def forbidden(_exc):
        msg = "Zugriff verweigert."
        if request.method == "POST":
            msg = "Sitzung abgelaufen oder ungültiges Formular. Bitte Seite neu laden."
        return render_template("error.html", code=403, message=msg), 403

    @app.errorhandler(404)
    def not_found(_exc):
        return render_template("error.html", code=404, message="Seite nicht gefunden."), 404

    @app.errorhandler(500)
    def server_error(_exc):
        return render_template("error.html", code=500, message="Interner Serverfehler."), 500

    return app


app = create_app()
