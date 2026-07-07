"""Flask-Anwendung – Simple Samba UI."""

from __future__ import annotations

import os
import secrets

from flask import Flask, Response, after_this_request, flash, jsonify, redirect, render_template, request, send_file, url_for

from app.auth import (
    attempt_login,
    configure_session,
    hash_password,
    is_authenticated,
    login_required,
    login_user,
    logout_user,
    safe_redirect_target,
    verify_password,
)
from app.csrf import get_csrf_token, validate_csrf_token
from app.config import load_config, save_config
from app.files import (
    FileBrowserError,
    cancel_download_job,
    cleanup_download_job,
    commit_upload,
    create_directory,
    delete_path,
    download_job_status,
    download_manifest,
    estimate_zip_download_size,
    iter_folder_zip,
    list_directory,
    stage_download,
    start_download_job,
)
from app.rate_limit import clear_login_attempts, is_login_locked, record_failed_login
from app.samba import (
    SambaError,
    Share,
    add_samba_user,
    delete_samba_user,
    delete_share_directory,
    get_share_by_name,
    import_shares,
    list_importable_shares,
    list_samba_users,
    read_shares,
    reload_samba,
    restart_samba,
    run_testparm,
    service_status,
    set_samba_password,
    write_shares,
)
from app.system import (
    SystemUpdateError,
    app_update_job_status,
    app_update_start,
    apt_job_status,
    apt_list_upgradable,
    apt_start_install_job,
    apt_update,
    check_upgradable_safe,
    format_bytes,
    format_uptime,
    get_overview_safe,
)
from app.app_updates import get_app_update_info
from app.network import resolve_access_host
from app.validators import (
    ValidationError,
    parse_valid_users_checked,
    validate_comment,
    validate_password,
    validate_samba_username,
    validate_share_name,
    validate_share_path,
)

FILE_STAGING_DIR = "/var/lib/samba-ui/file-staging"
INITIAL_PASSWORD_FILE = "/etc/simple-samba-ui/initial-password.txt"


def _cleanup_staged_download(path: str, direct: bool = False) -> None:
    if direct or not path.startswith(FILE_STAGING_DIR + "/"):
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024
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

  # --- Auth ---

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if is_authenticated():
            return redirect(url_for("index"))
        error = None
        client_ip = request.remote_addr or "unknown"
        locked, wait_seconds = is_login_locked(client_ip)
        if request.method == "POST":
            if locked:
                minutes = max(1, wait_seconds // 60)
                error = f"Zu viele Fehlversuche. Bitte ca. {minutes} Min. warten."
            else:
                username = (request.form.get("username") or "").strip()
                password = request.form.get("password") or ""
                if attempt_login(username, password):
                    clear_login_attempts(client_ip)
                    login_user(username)
                    next_url = safe_redirect_target(request.args.get("next"), url_for("index"))
                    return redirect(next_url)
                record_failed_login(client_ip)
                locked, wait_seconds = is_login_locked(client_ip)
                if locked:
                    minutes = max(1, wait_seconds // 60)
                    error = f"Zu viele Fehlversuche. Bitte ca. {minutes} Min. warten."
                else:
                    error = "Ungültiger Benutzername oder Passwort."
        elif locked:
            minutes = max(1, wait_seconds // 60)
            error = f"Zu viele Fehlversuche. Bitte ca. {minutes} Min. warten."
        return render_template("login.html", error=error)

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
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

  # --- Dashboard ---

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

  # --- Shares ---

    @app.route("/shares/new", methods=["GET", "POST"])
    @login_required
    def share_new():
        config = load_config()
        share = Share(name="", path=_default_share_path(config["shares_base_path"]), comment="")
        error = None
        samba_users = _load_samba_users_for_form()
        if request.method == "POST":
            try:
                share = _share_from_form(request.form)
                shares = read_shares(config["samba_shares_file"])
                if get_share_by_name(shares, share.name):
                    raise ValidationError(f"Freigabe „{share.name}“ existiert bereits.")
                shares.append(share)
                write_shares(shares, config["samba_shares_file"], config["shares_base_path"])
                host = resolve_access_host(config.get("bind_host", "0.0.0.0"))
                flash(
                    f"Freigabe „{share.name}“ erstellt. Sofort zugreifbar unter "
                    f"\\\\{host}\\{share.name} (Samba-Benutzer erforderlich).",
                    "success",
                )
                return redirect(url_for("index"))
            except (ValidationError, SambaError) as exc:
                error = str(exc)
                share = _share_from_form_values(request.form)
        return render_template(
            "share_form.html", share=share, error=error, editing=False, samba_users=samba_users
        )

    @app.route("/shares/<path:share_name>/edit", methods=["GET", "POST"])
    @login_required
    def share_edit(share_name: str):
        config = load_config()
        shares = read_shares(config["samba_shares_file"])
        existing = get_share_by_name(shares, share_name)
        if not existing:
            flash("Freigabe nicht gefunden.", "error")
            return redirect(url_for("index"))
        error = None
        samba_users = _load_samba_users_for_form()
        if request.method == "POST":
            try:
                updated = _share_from_form(request.form)
                new_name = updated.name
                if new_name != share_name and get_share_by_name(shares, new_name):
                    raise ValidationError(f"Freigabe „{new_name}“ existiert bereits.")
                shares = [s for s in shares if s.name != share_name]
                shares.append(updated)
                write_shares(shares, config["samba_shares_file"], config["shares_base_path"])
                flash(f"Freigabe „{new_name}“ wurde aktualisiert.", "success")
                return redirect(url_for("index"))
            except (ValidationError, SambaError) as exc:
                error = str(exc)
                existing = _share_from_form_values(request.form)
        return render_template(
            "share_form.html", share=existing, error=error, editing=True, samba_users=samba_users
        )

    @app.route("/shares/<path:share_name>/delete", methods=["GET", "POST"])
    @login_required
    def share_delete(share_name: str):
        config = load_config()
        try:
            shares = read_shares(config["samba_shares_file"])
            share = get_share_by_name(shares, share_name)
            if not share:
                flash("Freigabe nicht gefunden.", "error")
                return redirect(url_for("index"))

            if request.method == "GET":
                return render_template("share_delete.html", share=share)

            delete_files = request.form.get("delete_files") == "on"
            share_path = share.path
            shares = [s for s in shares if s.name != share_name]
            write_shares(shares, config["samba_shares_file"], config["shares_base_path"])

            if delete_files:
                delete_share_directory(share_path, config["shares_base_path"])
                flash(
                    f"Freigabe „{share_name}“ und Verzeichnis „{share_path}“ wurden gelöscht.",
                    "success",
                )
            else:
                flash(f"Freigabe „{share_name}“ wurde gelöscht. Daten unter {share_path} bleiben erhalten.", "success")
        except (ValidationError, SambaError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("index"))

    @app.route("/freigaben/importieren", methods=["GET", "POST"])
    @login_required
    def share_import():
        config = load_config()
        error = None
        importable: list[dict] = []
        list_error: str | None = None
        shares_base = config.get("shares_base_path", "/srv/shares")

        try:
            data = list_importable_shares()
            importable = data.get("importable") or []
            list_error = data.get("error")
            shares_base = data.get("shares_base_path") or shares_base
        except SambaError as exc:
            list_error = str(exc)

        if request.method == "POST":
            selected = request.form.getlist("share_names")
            comment_out = request.form.get("comment_out_source") == "on"
            try:
                if not selected:
                    raise ValidationError("Bitte mindestens eine Freigabe auswählen.")
                import_shares(selected, comment_out_source=comment_out)
                flash(
                    f"{len(selected)} Freigabe(n) importiert und in smb-shares.conf übernommen.",
                    "success",
                )
                return redirect(url_for("index"))
            except (ValidationError, SambaError) as exc:
                error = str(exc)

        return render_template(
            "share_import.html",
            importable=importable,
            list_error=list_error,
            error=error,
            shares_base=shares_base,
        )

    @app.route("/shares/<path:share_name>/toggle", methods=["POST"])
    @login_required
    def share_toggle(share_name: str):
        config = load_config()
        try:
            shares = read_shares(config["samba_shares_file"])
            found = False
            for share in shares:
                if share.name == share_name:
                    share.enabled = not share.enabled
                    found = True
                    break
            if not found:
                flash("Freigabe nicht gefunden.", "error")
                return redirect(url_for("index"))
            write_shares(shares, config["samba_shares_file"], config["shares_base_path"])
            state = "aktiviert" if share.enabled else "deaktiviert"
            flash(f"Freigabe „{share_name}“ wurde {state}.", "success")
        except SambaError as exc:
            flash(str(exc), "error")
        return redirect(url_for("index"))

  # --- Samba Users ---

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
            flash(f"Samba-Benutzer „{username}“ wurde gelöscht.", "success")
        except (ValidationError, SambaError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("users_list"))

  # --- Datei-Explorer ---

    @app.route("/dateien")
    @login_required
    def files_browser():
        config = load_config()
        try:
            shares = [s for s in read_shares(config["samba_shares_file"]) if s.enabled]
        except SambaError as exc:
            flash(str(exc), "error")
            shares = []
        return render_template(
            "files.html",
            shares=shares,
            shares_boot=[
                {"name": s.name, "path": s.path, "readOnly": s.read_only}
                for s in shares
            ],
        )

    @app.route("/api/files/browse")
    @login_required
    def files_api_browse():
        share_name = request.args.get("share", "")
        rel_path = request.args.get("path", "")
        try:
            data = list_directory(share_name, rel_path)
            return jsonify(data)
        except (ValidationError, FileBrowserError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/files/download")
    @login_required
    def files_api_download():
        """Synchroner Download (Vorschaubilder)."""
        share_name = request.args.get("share", "")
        rel_path = request.args.get("path", "")
        job_id = request.args.get("job", "")
        try:
            direct = False
            if job_id:
                status = download_job_status(job_id)
                if status.get("status") != "ready":
                    return jsonify({"error": "Download noch nicht bereit."}), 409
                source_path = status.get("staging") or ""
                name = status.get("name") or "download"
                direct = bool(status.get("direct"))
            else:
                info = stage_download(share_name, rel_path)
                source_path = info.get("path") or info.get("staging") or ""
                name = info.get("name") or "download"
                direct = bool(info.get("direct", True))
                job_id = ""

            @after_this_request
            def _cleanup(response):
                _cleanup_staged_download(source_path, direct)
                if job_id:
                    try:
                        cleanup_download_job(job_id)
                    except FileBrowserError:
                        pass
                return response

            return send_file(
                source_path,
                as_attachment=True,
                download_name=name,
                mimetype="application/octet-stream",
            )
        except (ValidationError, FileBrowserError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/files/download/start", methods=["POST"])
    @login_required
    def files_api_download_start():
        data = request.get_json(silent=True) or {}
        try:
            job_id = start_download_job(
                str(data.get("share", "")),
                str(data.get("path", "")),
            )
            return jsonify({"ok": True, "job_id": job_id})
        except (ValidationError, FileBrowserError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/files/download/status")
    @login_required
    def files_api_download_status():
        job_id = request.args.get("job", "")
        try:
            return jsonify(download_job_status(job_id))
        except (ValidationError, FileBrowserError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/files/download/manifest")
    @login_required
    def files_api_download_manifest():
        share_name = request.args.get("share", "")
        rel_path = request.args.get("path", "")
        try:
            return jsonify(download_manifest(share_name, rel_path))
        except (ValidationError, FileBrowserError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/files/download/folder")
    @login_required
    def files_api_download_folder():
        share_name = request.args.get("share", "")
        rel_path = request.args.get("path", "")
        try:
            manifest = download_manifest(share_name, rel_path)
            folder_name = manifest.get("name") or "ordner"
            estimated_size = estimate_zip_download_size(manifest)
            return Response(
                iter_folder_zip(share_name, rel_path),
                mimetype="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="{folder_name}.zip"',
                    "X-Download-Total-Bytes": str(estimated_size),
                },
            )
        except (ValidationError, FileBrowserError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/files/download/cancel", methods=["POST"])
    @login_required
    def files_api_download_cancel():
        data = request.get_json(silent=True) or {}
        try:
            cancel_download_job(str(data.get("job", "")))
            return jsonify({"ok": True})
        except (ValidationError, FileBrowserError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/files/upload", methods=["POST"])
    @login_required
    def files_api_upload():
        share_name = request.form.get("share", "")
        rel_path = request.form.get("path", "")
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return jsonify({"error": "Keine Datei ausgewählt."}), 400

        filename = os.path.basename(uploaded.filename.replace("\\", "/"))
        if not filename or filename in (".", ".."):
            return jsonify({"error": "Ungültiger Dateiname."}), 400

        os.makedirs(FILE_STAGING_DIR, exist_ok=True)
        token = secrets.token_hex(16)
        staging = os.path.join(FILE_STAGING_DIR, f"upload-{token}-{filename}")
        try:
            uploaded.save(staging)
            os.chmod(staging, 0o640)
            commit_upload(share_name, rel_path, staging, filename)
            return jsonify({"ok": True, "name": filename})
        except (ValidationError, FileBrowserError) as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            try:
                os.unlink(staging)
            except OSError:
                pass

    @app.route("/api/files/mkdir", methods=["POST"])
    @login_required
    def files_api_mkdir():
        data = request.get_json(silent=True) or {}
        try:
            create_directory(
                str(data.get("share", "")),
                str(data.get("path", "")),
                str(data.get("name", "")),
            )
            return jsonify({"ok": True})
        except (ValidationError, FileBrowserError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/files/delete", methods=["POST"])
    @login_required
    def files_api_delete():
        data = request.get_json(silent=True) or {}
        try:
            delete_path(str(data.get("share", "")), str(data.get("path", "")))
            return jsonify({"ok": True})
        except (ValidationError, FileBrowserError) as exc:
            return jsonify({"error": str(exc)}), 400

  # --- Service / Diagnostics ---

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


def _default_share_path(base_path: str) -> str:
    return f"{base_path.rstrip('/')}/"


def _load_samba_users_for_form() -> list[str]:
    try:
        return list_samba_users()
    except SambaError:
        return []


def _share_from_form_values(form) -> Share:
    """Formularwerte ohne Validierung (Anzeige nach Fehler)."""
    guest_ok = form.get("guest_ok") == "on"
    return Share(
        name=(form.get("name") or "").strip(),
        path=(form.get("path") or "").strip(),
        comment=(form.get("comment") or "").strip(),
        browseable=form.get("browseable") == "on",
        read_only=form.get("read_only") == "on",
        guest_ok=guest_ok,
        valid_users=[] if guest_ok else form.getlist("valid_users"),
        enabled=form.get("enabled", "on") == "on",
    )


def _share_from_form(form) -> Share:
    config = load_config()
    name = validate_share_name(form.get("name") or "")
    path = validate_share_path(form.get("path") or "", config["shares_base_path"])
    comment = validate_comment(form.get("comment"))
    guest_ok = form.get("guest_ok") == "on"
    if guest_ok:
        valid_users = []
    else:
        valid_users = parse_valid_users_checked(form.getlist("valid_users"))
        if not valid_users:
            raise ValidationError(
                "Mindestens einen Samba-Benutzer auswählen oder Gast-Zugriff aktivieren."
            )
    return Share(
        name=name,
        path=path,
        comment=comment,
        browseable=form.get("browseable") == "on",
        read_only=form.get("read_only") == "on",
        guest_ok=guest_ok,
        valid_users=valid_users,
        enabled=form.get("enabled", "on") == "on",
    )


app = create_app()
