"""Datei-Explorer – Browse, Upload und Download innerhalb von Freigaben."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import load_config
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
    share_root = Path(share.path).resolve()
    base = Path(base_path).resolve()
    try:
        share_root.relative_to(base)
    except ValueError as exc:
        raise ValidationError(f"Freigabepfad liegt nicht unter {base}.") from exc

    rel = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        raise ValidationError("Ungültiger Pfad.")

    if not rel:
        return str(share_root)

    target = (share_root / rel).resolve()
    try:
        target.relative_to(share_root)
    except ValueError as exc:
        raise ValidationError("Pfad liegt außerhalb der Freigabe.") from exc
    return str(target)


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


def commit_upload(share_name: str, rel_dir: str, staging_path: str) -> None:
    config = load_config()
    shares = read_shares(config["samba_shares_file"])
    share = _share_for_name(shares, share_name)
    if share.read_only:
        raise FileBrowserError("Freigabe ist schreibgeschützt.")
    parent = resolve_browser_path(share, rel_dir, config["shares_base_path"])
    payload = json.dumps({"parent": parent, "staging": staging_path})
    ok, detail = _priv_request("files-commit-upload", body=payload)
    if not ok:
        raise FileBrowserError(detail or "Upload fehlgeschlagen.")
