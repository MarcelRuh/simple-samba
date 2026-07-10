"""System-Updates und Neustart."""

from __future__ import annotations

from flask import Flask, flash, jsonify, render_template, request

from app.app_updates import get_app_update_info
from app.audit import audit_log
from app.auth import login_required
from app.config import load_config
from app.system import (
    SystemUpdateError,
    app_update_job_status,
    app_update_start,
    apt_job_status,
    apt_list_upgradable,
    apt_start_install_job,
    apt_update,
    check_upgradable_safe,
    get_overview_safe,
    system_reboot,
)


def register(app: Flask) -> None:
    @app.route("/system/updates", methods=["GET", "POST"])
    @login_required
    def system_updates():
        upgradable_packages: list[str] = []
        check_error: str | None = None
        last_output: str | None = None
        last_success: bool | None = None
        job_running = False
        app_job_running = False

        try:
            job = apt_job_status()
            job_running = job.get("status") == "running"
        except SystemUpdateError:
            job = {"status": "idle"}

        try:
            app_job = app_update_job_status()
            app_job_running = app_job.get("status") == "running"
        except SystemUpdateError:
            app_job = {"status": "idle"}

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            try:
                if action == "update":
                    last_output = apt_update()
                    last_success = True
                    audit_log("system.apt_update")
                    flash("Paketlisten wurden aktualisiert.", "success")
                    try:
                        upgradable_packages, check_out = apt_list_upgradable()
                        if upgradable_packages:
                            last_output = f"{last_output}\n\n{check_out}"
                        else:
                            last_output = (
                                f"{last_output}\n\n"
                                "Keine aktualisierbaren Pakete (System ist aktuell)."
                            )
                    except SystemUpdateError:
                        pass
                else:
                    flash("Unbekannte Aktion.", "error")
            except SystemUpdateError as exc:
                last_output = str(exc)
                last_success = False
                flash(str(exc).splitlines()[0], "error")

        if not upgradable_packages:
            upgradable_packages, err = check_upgradable_safe()
            if err and not check_error:
                check_error = err

        from app import __version__

        cfg = load_config()
        force_app_check = request.args.get("check_app") == "1"
        app_update = get_app_update_info(cfg, __version__, force_refresh=force_app_check)
        overview, _overview_err = get_overview_safe()

        return render_template(
            "system_updates.html",
            upgradable_packages=upgradable_packages,
            upgradable_count=len(upgradable_packages),
            check_error=check_error,
            last_output=last_output,
            last_success=last_success,
            job_running=job_running,
            job=job,
            app_update=app_update,
            app_job_running=app_job_running,
            app_job=app_job,
            reboot_required=bool(overview and overview.reboot_required),
            reboot_reason=overview.reboot_reason if overview else "",
        )

    @app.route("/system/updates/job/start", methods=["POST"])
    @login_required
    def system_updates_job_start():
        try:
            apt_start_install_job()
            return jsonify({"ok": True, "status": "running"})
        except SystemUpdateError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/system/updates/job")
    @login_required
    def system_updates_job():
        try:
            return jsonify(apt_job_status())
        except SystemUpdateError as exc:
            return jsonify({"status": "error", "error": str(exc)}), 500

    @app.route("/system/updates/app/start", methods=["POST"])
    @login_required
    def system_updates_app_start():
        try:
            app_update_start()
            audit_log("system.app_update")
            return jsonify({"ok": True, "status": "running"})
        except SystemUpdateError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/system/updates/app/job")
    @login_required
    def system_updates_app_job():
        try:
            return jsonify(app_update_job_status())
        except SystemUpdateError as exc:
            return jsonify({"status": "error", "error": str(exc)}), 500

    @app.route("/system/updates/reboot", methods=["POST"])
    @login_required
    def system_updates_reboot():
        try:
            message = system_reboot()
            audit_log("system.reboot")
            return jsonify({"ok": True, "message": message})
        except SystemUpdateError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
