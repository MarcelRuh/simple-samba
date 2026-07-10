"""Datei-Explorer – Browse, Upload und Download innerhalb von Freigaben."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import DEFAULT_MAX_FOLDER_DOWNLOAD_BYTES, DEFAULT_MAX_FOLDER_DOWNLOAD_FILES, load_config
from app.path_security import safe_resolve_under_root
from app.samba import Share, SambaError, _priv_request, get_share_by_name, read_shares
from app.validators import ValidationError, validate_share_name


class FileBrowserError(Exception):
    """Fehler beim Dateizugriff."""


def _share_for_name(shares: list[Share], name: str) -> Share:
    share = get_share_by_name(shares, validate_share_name(name))
    if not share:
        raise FileBrowserError(f"Freigabe „{name}“ nicht gefunden.")
    if not share.enabled:
        raise FileBrowserError(f"Freigabe „{name}“ ist deaktiviert.")
    return share


def resolve_browser_path(share: Share, rel_path: str, base_path: str) -> str:
    """Löst einen relativen Pfad innerhalb einer Freigabe auf."""
    share_root = Path(share.path)
    base = Path(base_path).resolve()
    try:
        share_root.resolve().relative_to(base)
    except ValueError as exc:
        raise ValidationError(f"Freigabepfad liegt nicht unter {base}.") from exc

    rel = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    return str(safe_resolve_under_root(share_root, rel))


def list_directory(share_name: str, rel_path: str = "") -> dict[str, Any]:
    config = load_config()
    shares = read_shares(config["samba_shares_file"])
    share = _share_for_name(shares, share_name)
    abs_path = resolve_browser_path(share, rel_path, config["shares_base_path"])
    ok, output = _priv_request("files-list", arg=abs_path)
    if not ok:
        raise FileBrowserError(output or "Verzeichnis konnte nicht gelesen werden.")
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise FileBrowserError("Ungültige Antwort vom Server.") from exc

    share_root = Path(share.path).resolve()
    abs_path = Path(data["path"]).resolve()
    rel = abs_path.relative_to(share_root)
    rel_str = "" if str(rel) in ("", ".") else str(rel).replace("\\", "/")
    parent_rel = ""
    if rel_str:
        parent = Path(rel_str).parent
        parent_rel = "" if str(parent) in ("", ".") else str(parent).replace("\\", "/")

    data["rel_path"] = rel_str
    data["parent_rel"] = parent_rel
    data["share"] = share.name
    data["read_only"] = share.read_only
    data["share_path"] = share.path
    return data


def create_directory(share_name: str, rel_path: str, folder_name: str) -> None:
    config = load_config()
    shares = read_shares(config["samba_shares_file"])
    share = _share_for_name(shares, share_name)
    if share.read_only:
        raise FileBrowserError("Freigabe ist schreibgeschützt.")
    folder = (folder_name or "").strip()
    if not folder or "/" in folder or "\\" in folder or folder in (".", ".."):
        raise ValidationError("Ungültiger Ordnername.")
    parent = resolve_browser_path(share, rel_path, config["shares_base_path"])
    target = str((Path(parent) / folder).resolve())
    ok, detail = _priv_request("files-mkdir", arg=target)
    if not ok:
        raise FileBrowserError(detail or "Ordner konnte nicht erstellt werden.")


def delete_path(share_name: str, rel_path: str) -> None:
    config = load_config()
    shares = read_shares(config["samba_shares_file"])
    share = _share_for_name(shares, share_name)
    if share.read_only:
        raise FileBrowserError("Freigabe ist schreibgeschützt.")
    if not (rel_path or "").strip():
        raise ValidationError("Freigabe-Wurzelverzeichnis kann nicht gelöscht werden.")
    abs_path = resolve_browser_path(share, rel_path, config["shares_base_path"])
    ok, detail = _priv_request("files-delete", arg=abs_path)
    if not ok:
        raise FileBrowserError(detail or "Löschen fehlgeschlagen.")


def stage_download(share_name: str, rel_path: str) -> dict[str, Any]:
    config = load_config()
    shares = read_shares(config["samba_shares_file"])
    share = _share_for_name(shares, share_name)
    if not (rel_path or "").strip():
        raise ValidationError("Dateiname fehlt.")
    abs_path = resolve_browser_path(share, rel_path, config["shares_base_path"])
    ok, output = _priv_request("files-stage-download", arg=abs_path)
    if not ok:
        raise FileBrowserError(output or "Download konnte nicht vorbereitet werden.")
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise FileBrowserError("Ungültige Antwort vom Server.") from exc


def validate_folder_download_manifest(manifest: dict[str, Any], config: dict[str, Any] | None = None) -> None:
    cfg = config or load_config()
    max_files = int(cfg.get("max_folder_download_files", DEFAULT_MAX_FOLDER_DOWNLOAD_FILES))
    max_bytes = int(cfg.get("max_folder_download_bytes", DEFAULT_MAX_FOLDER_DOWNLOAD_BYTES))
    file_count = int(manifest.get("total_files") or len(manifest.get("files") or []))
    total_size = int(manifest.get("total_size") or 0)
    if file_count > max_files:
        raise FileBrowserError(
            f"Ordner enthält zu viele Dateien für ZIP-Download (Limit: {max_files:,})."
        )
    if total_size > max_bytes:
        raise FileBrowserError(
            f"Ordner ist zu groß für ZIP-Download (Limit: {max_bytes // (1024 * 1024):,} MiB)."
        )


def download_manifest(share_name: str, rel_path: str) -> dict[str, Any]:
    config = load_config()
    shares = read_shares(config["samba_shares_file"])
    share = _share_for_name(shares, share_name)
    if not (rel_path or "").strip():
        raise ValidationError("Ordnerpfad fehlt.")
    abs_path = resolve_browser_path(share, rel_path, config["shares_base_path"])
    ok, output = _priv_request("files-download-manifest", arg=abs_path)
    if not ok:
        raise FileBrowserError(output or "Ordnerinhalt konnte nicht gelesen werden.")
    try:
        manifest = json.loads(output)
    except json.JSONDecodeError as exc:
        raise FileBrowserError("Ungültige Antwort vom Server.") from exc
    validate_folder_download_manifest(manifest, config)
    return manifest


def estimate_zip_download_size(manifest: dict[str, Any]) -> int:
    files = manifest.get("files") or []
    total_size = int(manifest.get("total_size") or 0)
    if not total_size:
        total_size = sum(int(entry.get("size") or 0) for entry in files)
    file_count = int(manifest.get("total_files") or len(files))
    return total_size + file_count * 128 + 4096


def iter_folder_zip(share_name: str, rel_path: str) -> Any:
    """Streamt einen Ordner als ZIP direkt von der Freigabe (ohne Staging-Kopie)."""
    from zipstream import ZIP_STORED, ZipStream

    manifest = download_manifest(share_name, rel_path)
    folder_name = manifest.get("name") or "ordner"
    config = load_config()
    shares = read_shares(config["samba_shares_file"])
    share = _share_for_name(shares, share_name)
    base = config["shares_base_path"]

    zs = ZipStream(compress_type=ZIP_STORED)
    for entry in manifest.get("files", []):
        rel = str(entry.get("rel", "")).strip()
        if not rel:
            continue
        inner_rel = f"{rel_path}/{rel}" if rel_path else rel
        abs_path = resolve_browser_path(share, inner_rel, base)
        path = Path(abs_path)
        if not path.is_file():
            continue
        zs.add_path(str(path), arcname=f"{folder_name}/{rel}")

    if zs.is_empty():
        raise FileBrowserError("Der Ordner enthält keine Dateien.")

    yield from zs


def commit_upload(share_name: str, rel_dir: str, staging_path: str, filename: str) -> None:
    config = load_config()
    shares = read_shares(config["samba_shares_file"])
    share = _share_for_name(shares, share_name)
    if share.read_only:
        raise FileBrowserError("Freigabe ist schreibgeschützt.")
    parent = resolve_browser_path(share, rel_dir, config["shares_base_path"])
    payload = json.dumps({"parent": parent, "staging": staging_path, "filename": filename})
    ok, detail = _priv_request("files-commit-upload", body=payload)
    if not ok:
        raise FileBrowserError(detail or "Upload fehlgeschlagen.")
