"""Dienststatus und Konfigurationsprüfung."""

from __future__ import annotations

from flask import Flask, flash, redirect, render_template, url_for

from app.auth import login_required
from app.samba import SambaError, reload_samba, restart_samba, run_testparm, service_status


def register(app: Flask) -> None:
    @app.route("/status")
    @login_required
    def status_page():
        try:
            status = service_status()
            config_check = run_testparm()
        except SambaError as exc:
            flash(str(exc), "error")
            status = {"active": "unknown", "is_running": False, "output": ""}
            config_check = {"success": False, "output": str(exc)}
        return render_template("status.html", status=status, config_check=config_check)

    @app.route("/service/reload", methods=["POST"])
    @login_required
    def service_reload():
        try:
            reload_samba()
            flash("Samba-Dienst (smbd) wurde neu geladen.", "success")
        except SambaError as exc:
            flash(str(exc), "error")
        return redirect(url_for("status_page"))

    @app.route("/service/restart", methods=["POST"])
    @login_required
    def service_restart():
        try:
            restart_samba()
            flash("Samba-Dienst (smbd) wurde neu gestartet.", "success")
        except SambaError as exc:
            flash(str(exc), "error")
        return redirect(url_for("status_page"))

    @app.route("/konfiguration/pruefen", methods=["GET", "POST"])
    @login_required
    def config_check_page():
        try:
            config_check = run_testparm()
        except SambaError as exc:
            config_check = {"success": False, "output": str(exc)}
        return render_template("config_check.html", config_check=config_check)

    @app.route("/testparm")
    @login_required
    def testparm_redirect():
        """Alte URL – Weiterleitung zur neuen Seite."""
        return redirect(url_for("config_check_page"))
