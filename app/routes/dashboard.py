"""Dashboard."""

from __future__ import annotations

import os

from flask import Flask, flash, render_template, url_for

from app import __version__
from app.app_updates import get_app_update_info
from app.auth import login_required
from app.config import load_config
from app.security_checks import share_security_warnings
from app.samba import SambaError, list_samba_users, read_shares, run_testparm, service_status
from app.system import format_bytes, format_uptime, get_overview_safe, get_smb_status_safe
from app.tls import is_tls_enabled

INITIAL_PASSWORD_FILE = "/etc/simple-samba-ui/initial-password.txt"


def _share_preview(shares: list, *, limit: int = 5) -> list:
    enabled = sorted(
        (s for s in shares if s.enabled),
        key=lambda item: item.name.lower(),
    )
    return enabled[:limit]


def _dashboard_warnings(
    *,
    status: dict,
    overview,
    overview_error: str | None,
    config_ok: bool | None,
    initial_password_exists: bool,
    app_update,
    shares: list,
    config,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []

    if not status.get("is_running"):
        warnings.append({
            "level": "error",
            "message": "Samba-Dienst (smbd) läuft nicht.",
            "action_url": url_for("status_page"),
            "action_label": "Status öffnen",
        })

    if config_ok is False:
        warnings.append({
            "level": "error",
            "message": "Samba-Konfiguration ist ungültig (testparm meldet Fehler).",
            "action_url": url_for("config_check_page"),
            "action_label": "Konfiguration prüfen",
        })

    if overview and overview.disk_percent > 85:
        warnings.append({
            "level": "warn",
            "message": f"Festplatte zu {overview.disk_percent:.0f}% belegt "
            f"({format_bytes(overview.disk_used)} / {format_bytes(overview.disk_total)}).",
            "action_url": url_for("system_updates"),
            "action_label": "Updates",
        })

    if overview and overview.mem_percent > 90:
        warnings.append({
            "level": "warn",
            "message": f"Arbeitsspeicher zu {overview.mem_percent:.0f}% belegt "
            f"({format_bytes(overview.mem_used)} / {format_bytes(overview.mem_total)}).",
            "action_url": url_for("status_page"),
            "action_label": "Status",
        })

    if overview and overview.cpu_count > 0 and overview.load_1 > overview.cpu_count * 1.5:
        warnings.append({
            "level": "warn",
            "message": f"Hohe Systemlast: Load {overview.load_1:.2f} "
            f"({overview.cpu_count} Kerne).",
            "action_url": url_for("status_page"),
            "action_label": "Status",
        })
    elif overview_error:
        warnings.append({
            "level": "warn",
            "message": f"Systemübersicht nicht verfügbar: {overview_error}",
            "action_url": url_for("status_page"),
            "action_label": "Status",
        })

    if overview and overview.reboot_required:
        reason = overview.reboot_reason or "Kernel oder Pakete erfordern einen Neustart."
        warnings.append({
            "level": "warn",
            "message": f"Neustart erforderlich: {reason}",
            "action_url": url_for("system_updates"),
            "action_label": "System-Updates",
        })

    if app_update and getattr(app_update, "update_available", False):
        latest = getattr(app_update, "latest_version", None) or "?"
        warnings.append({
            "level": "warn",
            "message": f"App-Update verfügbar: v{latest}.",
            "action_url": url_for("system_updates"),
            "action_label": "Update anzeigen",
        })

    if initial_password_exists:
        warnings.append({
            "level": "warn",
            "message": "Standard-Admin-Passwort wurde noch nicht geändert "
            "(initial-password.txt liegt noch vor).",
            "action_url": url_for("change_password"),
            "action_label": "Passwort ändern",
        })

    if config and not is_tls_enabled(config):
        warnings.append({
            "level": "warn",
            "message": "Web-UI läuft über HTTP – Ordner-Downloads werden als ZIP bereitgestellt. "
            "HTTPS aktivieren: sudo bash /opt/simple-samba-ui/scripts/enable-tls.sh",
            "action_url": "",
            "action_label": "",
        })

    for item in share_security_warnings(shares):
        warnings.append({
            "level": item["level"],
            "message": item["message"],
            "action_url": url_for("share_edit", share_name=item["share_name"]),
            "action_label": "Freigabe bearbeiten",
        })

    return warnings


def register(app: Flask) -> None:
    @app.route("/")
    @login_required
    def index():
        config = load_config()
        overview, overview_error = get_overview_safe()
        smb_status, smb_status_error = get_smb_status_safe()
        shares: list = []
        shares_active = 0
        shares_disabled = 0
        users_count = 0
        config_ok: bool | None = None
        status = {"active": "unknown", "is_running": False, "output": ""}

        try:
            shares = read_shares(config["samba_shares_file"])
            shares_active = sum(1 for share in shares if share.enabled)
            shares_disabled = len(shares) - shares_active
            status = service_status()
        except SambaError as exc:
            flash(str(exc), "error")

        try:
            users_count = len(list_samba_users())
        except SambaError:
            pass

        try:
            config_ok = bool(run_testparm().get("success"))
        except SambaError:
            config_ok = False

        share_preview = _share_preview(shares)
        smb_shares = sorted(
            (s for s in shares if s.enabled),
            key=lambda item: item.name.lower(),
        )
        app_update_info = get_app_update_info(config, __version__)
        initial_password_exists = os.path.isfile(INITIAL_PASSWORD_FILE)

        return render_template(
            "dashboard.html",
            shares=shares,
            shares_count=len(shares),
            shares_active=shares_active,
            shares_disabled=shares_disabled,
            share_preview=share_preview,
            smb_shares=smb_shares,
            users_count=users_count,
            config_ok=config_ok,
            status=status,
            config=config,
            overview=overview,
            overview_error=overview_error,
            smb_status=smb_status,
            smb_status_error=smb_status_error,
            initial_password_exists=initial_password_exists,
            dashboard_warnings=_dashboard_warnings(
                status=status,
                overview=overview,
                overview_error=overview_error,
                config_ok=config_ok,
                initial_password_exists=initial_password_exists,
                app_update=app_update_info,
                shares=shares,
                config=config,
            ),
            format_bytes=format_bytes,
            format_uptime=format_uptime,
        )
