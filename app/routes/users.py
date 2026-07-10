"""Samba-Benutzer verwalten."""

from __future__ import annotations

from flask import Flask, flash, redirect, render_template, request, url_for

from app.audit import audit_log
from app.auth import login_required
from app.samba import (
    SambaError,
    add_samba_user,
    delete_samba_user,
    list_samba_users,
    set_samba_password,
)
from app.validators import ValidationError, validate_password, validate_samba_username


def register(app: Flask) -> None:
    @app.route("/users")
    @login_required
    def users_list():
        try:
            users = list_samba_users()
        except SambaError as exc:
            flash(str(exc), "error")
            users = []
        return render_template("users.html", users=users)

    @app.route("/users/new", methods=["GET", "POST"])
    @login_required
    def user_new():
        error = None
        username = ""
        if request.method == "POST":
            try:
                username = validate_samba_username(request.form.get("username") or "")
                password = validate_password(request.form.get("password") or "")
                add_samba_user(username, password)
                audit_log("user.create", username)
                flash(f"Samba-Benutzer „{username}“ wurde angelegt.", "success")
                return redirect(url_for("users_list"))
            except (ValidationError, SambaError) as exc:
                error = str(exc)
                username = (request.form.get("username") or "").strip()
        return render_template("user_form.html", error=error, username=username, editing=False)

    @app.route("/users/<username>/password", methods=["GET", "POST"])
    @login_required
    def user_password(username: str):
        try:
            username = validate_samba_username(username)
        except ValidationError:
            flash("Ungültiger Benutzername.", "error")
            return redirect(url_for("users_list"))
        error = None
        if request.method == "POST":
            try:
                password = validate_password(request.form.get("password") or "")
                set_samba_password(username, password)
                audit_log("user.password", username)
                flash(f"Passwort für „{username}“ wurde geändert.", "success")
                return redirect(url_for("users_list"))
            except (ValidationError, SambaError) as exc:
                error = str(exc)
        return render_template("user_form.html", error=error, username=username, editing=True)

    @app.route("/users/<username>/delete", methods=["POST"])
    @login_required
    def user_delete(username: str):
        try:
            username = validate_samba_username(username)
            delete_samba_user(username)
            audit_log("user.delete", username)
            flash(f"Samba-Benutzer „{username}“ wurde gelöscht.", "success")
        except (ValidationError, SambaError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("users_list"))
