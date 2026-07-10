"""Audit-Protokoll und Konfigurations-Backups."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Flask, flash, redirect, render_template, request, url_for

from app.audit import ACTION_LABELS, audit_log, read_audit_log
from app.auth import login_required
from app.backups import BackupError, list_config_backups, restore_config_backup


def register(app: Flask) -> None:
    @app.route("/protokoll")
    @login_required
    def audit_log_page():
        return render_template(
            "audit_log.html",
            entries=read_audit_log(),
            action_labels=ACTION_LABELS,
        )

    @app.route("/backups", methods=["GET", "POST"])
    @login_required
    def backups_page():
        error = None
        backups: list = []
        try:
            backups = list_config_backups()
            for item in backups:
                mtime = int(item.get("mtime") or 0)
                item["mtime_fmt"] = (
                    datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
                    if mtime
                    else "–"
                )
                size = int(item.get("size") or 0)
                if size >= 1024 * 1024:
                    item["size_fmt"] = f"{size / (1024 * 1024):.1f} MiB"
                elif size >= 1024:
                    item["size_fmt"] = f"{size / 1024:.1f} KiB"
                else:
                    item["size_fmt"] = f"{size} B"
        except BackupError as exc:
            error = str(exc)

        if request.method == "POST":
            name = (request.form.get("backup_name") or "").strip()
            if not name:
                flash("Kein Backup ausgewählt.", "error")
            else:
                try:
                    message = restore_config_backup(name)
                    audit_log("backup.restore", name)
                    flash(message, "success")
                    return redirect(url_for("backups_page"))
                except BackupError as exc:
                    flash(str(exc), "error")
            try:
                backups = list_config_backups()
                for item in backups:
                    mtime = int(item.get("mtime") or 0)
                    item["mtime_fmt"] = (
                        datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
                        if mtime
                        else "–"
                    )
                    size = int(item.get("size") or 0)
                    if size >= 1024 * 1024:
                        item["size_fmt"] = f"{size / (1024 * 1024):.1f} MiB"
                    elif size >= 1024:
                        item["size_fmt"] = f"{size / 1024:.1f} KiB"
                    else:
                        item["size_fmt"] = f"{size} B"
            except BackupError as exc:
                error = str(exc)

        return render_template("backups.html", backups=backups, error=error)
