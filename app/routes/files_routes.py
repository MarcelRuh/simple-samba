"""Datei-Explorer und API."""

from __future__ import annotations

import os
import secrets

from flask import Flask, Response, after_this_request, flash, jsonify, render_template, request, send_file

from app.audit import audit_log
from app.auth import login_required
from app.config import load_config
from app.files import (
    FileBrowserError,
    commit_upload,
    create_directory,
    delete_path,
    download_manifest,
    estimate_zip_download_size,
    iter_folder_zip,
    list_directory,
    stage_download,
)
from app.samba import SambaError, read_shares
from app.validators import ValidationError

FILE_STAGING_DIR = "/var/lib/samba-ui/file-staging"


def _cleanup_staged_download(path: str, direct: bool = False) -> None:
    if direct or not path.startswith(FILE_STAGING_DIR + "/"):
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def register(app: Flask) -> None:
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
        """Synchroner Download (Vorschaubilder und Einzeldateien)."""
        share_name = request.args.get("share", "")
        rel_path = request.args.get("path", "")
        try:
            info = stage_download(share_name, rel_path)
            source_path = info.get("path") or info.get("staging") or ""
            name = info.get("name") or "download"
            direct = bool(info.get("direct", True))

            @after_this_request
            def _cleanup(response):
                _cleanup_staged_download(source_path, direct)
                return response

            return send_file(
                source_path,
                as_attachment=True,
                download_name=name,
                mimetype="application/octet-stream",
            )
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

    @app.route("/api/files/upload", methods=["POST"])
    @login_required
    def files_api_upload():
        share_name = request.form.get("share", "")
        rel_path = request.form.get("path", "")
        uploaded = request.files.get("file")
        if not uploaded:
            return jsonify({"error": "Keine Datei ausgewählt."}), 400

        raw_name = (request.form.get("filename") or uploaded.filename or "").strip()
        filename = os.path.basename(raw_name.replace("\\", "/"))
        if not filename or filename in (".", ".."):
            return jsonify({"error": "Ungültiger Dateiname."}), 400

        os.makedirs(FILE_STAGING_DIR, exist_ok=True)
        token = secrets.token_hex(16)
        staging = os.path.join(FILE_STAGING_DIR, f"upload-{token}-{filename}")
        try:
            uploaded.save(staging)
            os.chmod(staging, 0o640)
            commit_upload(share_name, rel_path, staging, filename)
            audit_log("file.upload", f"{share_name}:{rel_path}/{filename}")
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
            audit_log(
                "file.mkdir",
                f"{data.get('share', '')}:{data.get('path', '')}/{data.get('name', '')}",
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
            audit_log("file.delete", f"{data.get('share', '')}:{data.get('path', '')}")
            return jsonify({"ok": True})
        except (ValidationError, FileBrowserError) as exc:
            return jsonify({"error": str(exc)}), 400
