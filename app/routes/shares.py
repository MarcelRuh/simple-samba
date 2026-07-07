"""Samba-Freigaben verwalten."""

from __future__ import annotations

from flask import Flask, flash, redirect, render_template, request, url_for

from app.auth import login_required
from app.config import load_config
from app.network import resolve_access_host
from app.samba import (
    SambaError,
    Share,
    delete_share_directory,
    get_share_by_name,
    import_shares,
    list_importable_shares,
    read_shares,
    share_names_equal,
    write_shares,
)
from app.share_forms import (
    default_share_path,
    load_samba_users_for_form,
    share_from_form,
    share_from_form_values,
)
from app.validators import ValidationError


def register(app: Flask) -> None:
    @app.route("/shares/new", methods=["GET", "POST"])
    @login_required
    def share_new():
        config = load_config()
        share = Share(name="", path=default_share_path(config["shares_base_path"]), comment="")
        error = None
        samba_users = load_samba_users_for_form()
        if request.method == "POST":
            try:
                share = share_from_form(request.form)
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
                share = share_from_form_values(request.form)
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
        samba_users = load_samba_users_for_form()
        if request.method == "POST":
            try:
                updated = share_from_form(request.form)
                new_name = updated.name
                if not share_names_equal(new_name, share_name) and get_share_by_name(shares, new_name):
                    raise ValidationError(f"Freigabe „{new_name}“ existiert bereits.")
                shares = [s for s in shares if not share_names_equal(s.name, share_name)]
                shares.append(updated)
                write_shares(shares, config["samba_shares_file"], config["shares_base_path"])
                flash(f"Freigabe „{new_name}“ wurde aktualisiert.", "success")
                return redirect(url_for("index"))
            except (ValidationError, SambaError) as exc:
                error = str(exc)
                existing = share_from_form_values(request.form)
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
            shares = [s for s in shares if not share_names_equal(s.name, share_name)]
            write_shares(shares, config["samba_shares_file"], config["shares_base_path"])

            if delete_files:
                delete_share_directory(share_path, config["shares_base_path"])
                flash(
                    f"Freigabe „{share.name}“ und Verzeichnis „{share_path}“ wurden gelöscht.",
                    "success",
                )
            else:
                flash(
                    f"Freigabe „{share.name}“ wurde gelöscht. Daten unter {share_path} bleiben erhalten.",
                    "success",
                )
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
            share = get_share_by_name(shares, share_name)
            if not share:
                flash("Freigabe nicht gefunden.", "error")
                return redirect(url_for("index"))
            share.enabled = not share.enabled
            write_shares(shares, config["samba_shares_file"], config["shares_base_path"])
            state = "aktiviert" if share.enabled else "deaktiviert"
            flash(f"Freigabe „{share.name}“ wurde {state}.", "success")
        except SambaError as exc:
            flash(str(exc), "error")
        return redirect(url_for("index"))
