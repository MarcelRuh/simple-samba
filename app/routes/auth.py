"""Login, Logout und Admin-Passwort."""

from __future__ import annotations

import os

from flask import Flask, redirect, render_template, request, session, url_for

from app.audit import audit_log
from app.auth import (
    attempt_login,
    hash_password,
    login_required,
    login_user,
    logout_user,
    safe_redirect_target,
    verify_password,
    is_authenticated,
)
from app.config import load_config, save_config
from app.validators import ValidationError, validate_password

INITIAL_PASSWORD_FILE = "/etc/simple-samba-ui/initial-password.txt"


def register(app: Flask) -> None:
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if is_authenticated():
            return redirect(url_for("index"))
        error = None
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            if attempt_login(username, password):
                login_user(username)
                audit_log("auth.login", "success", user=username)
                next_url = safe_redirect_target(request.args.get("next"), url_for("index"))
                return redirect(next_url)
            audit_log("auth.login_failed", f"user={username}", user=username)
            error = "Ungültiger Benutzername oder Passwort."
        return render_template("login.html", error=error)

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        user = session.get("username", "admin")
        logout_user()
        audit_log("auth.logout", user=user)
        return redirect(url_for("login"))

    @app.route("/change-password", methods=["GET", "POST"])
    @login_required
    def change_password():
        error = None
        success = None
        initial_password_exists = os.path.isfile(INITIAL_PASSWORD_FILE)
        if request.method == "POST":
            current = request.form.get("current_password") or ""
            new_pw = request.form.get("new_password") or ""
            confirm = request.form.get("confirm_password") or ""
            config = load_config()
            if not verify_password(current, config["admin_password_hash"]):
                error = "Aktuelles Passwort ist falsch."
            elif new_pw != confirm:
                error = "Neue Passwörter stimmen nicht überein."
            else:
                try:
                    validate_password(new_pw, "Neues Passwort")
                    config["admin_password_hash"] = hash_password(new_pw)
                    save_config(config)
                    audit_log("auth.password_changed")
                    try:
                        os.unlink(INITIAL_PASSWORD_FILE)
                        initial_password_exists = False
                    except OSError:
                        pass
                    success = "Admin-Passwort wurde geändert."
                except ValidationError as exc:
                    error = str(exc)
        return render_template(
            "change_password.html",
            error=error,
            success=success,
            initial_password_exists=initial_password_exists,
        )
