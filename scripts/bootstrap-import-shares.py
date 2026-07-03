#!/usr/bin/env python3
"""Automatischer Import bestehender smb.conf-Freigaben bei der Installation."""

from __future__ import annotations

import configparser
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

INSTALL_ROOT = Path("/opt/simple-samba-ui")
SMB_CONF = Path("/etc/samba/smb.conf")
CONFIG_PATH = Path("/etc/simple-samba-ui/config.json")
BACKUP_DIR = Path("/var/backups/simple-samba-ui")


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _ensure_import_path() -> None:
    root = str(INSTALL_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _load_config() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _save_config_shares_base(new_base: str) -> None:
    cfg = _load_config()
    if cfg.get("shares_base_path") == new_base:
        return
    cfg["shares_base_path"] = new_base
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(CONFIG_PATH, 0o600)
    try:
        import pwd

        uid = pwd.getpwnam("samba-ui").pw_uid
        gid = pwd.getpwnam("samba-ui").pw_gid
        os.chown(CONFIG_PATH, uid, gid)
    except KeyError:
        pass
    _log(f"Basisverzeichnis angepasst: {new_base}")


def _backup_config_file(path: Path) -> None:
    if not path.is_file():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True, mode=0o750)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_name = path.name.replace("/", "_")
    shutil.copy2(path, BACKUP_DIR / f"{safe_name}.{ts}.bak")


def main() -> int:
    _ensure_import_path()
    from app.samba import Share, read_shares, shares_to_config_content
    from app.smbconf_parser import (
        comment_out_shares_in_files,
        filter_importable,
        infer_shares_base_path,
        parse_all_smb_conf_shares_with_sources,
        repair_smb_conf_include,
    )

    if not SMB_CONF.is_file():
        _log("Keine smb.conf – Import übersprungen.")
        return 0

    if repair_smb_conf_include(SMB_CONF):
        _log("Include-Zeile in [global] repariert.")

    try:
        located_shares = parse_all_smb_conf_shares_with_sources(SMB_CONF)
    except (OSError, configparser.Error) as exc:
        _log(f"smb.conf nicht lesbar: {exc}")
        return 1

    if not located_shares:
        _log("Keine Freigaben in smb.conf gefunden.")
        return 0

    smbconf_shares = [item.share for item in located_shares]
    cfg = _load_config()
    shares_file = Path(cfg.get("samba_shares_file") or "/etc/samba/smb-shares.conf")
    existing = read_shares(str(shares_file)) if shares_file.is_file() else []
    importable = filter_importable(smbconf_shares, {share.name for share in existing})
    if not importable:
        _log("Alle smb.conf-Freigaben sind bereits importiert.")
        return 0

    import_names = {share.name for share in importable}
    all_paths = [share.path for share in existing] + [share.path for share in importable]
    current_base = cfg.get("shares_base_path", "/srv/shares")
    new_base = infer_shares_base_path(all_paths, default=current_base)
    if new_base != current_base:
        _save_config_shares_base(new_base)

    merged: list[Share] = list(existing)
    for parsed in importable:
        merged.append(
            Share(
                name=parsed.name,
                path=parsed.path,
                comment=parsed.comment,
                browseable=parsed.browseable,
                read_only=parsed.read_only,
                guest_ok=parsed.guest_ok,
                valid_users=list(parsed.valid_users),
                enabled=parsed.enabled,
                create_mask=parsed.create_mask,
                directory_mask=parsed.directory_mask,
            )
        )

    shares_file.parent.mkdir(parents=True, exist_ok=True)
    shares_file.write_text(shares_to_config_content(merged), encoding="utf-8")
    os.chmod(shares_file, 0o644)

    for source_path, content in comment_out_shares_in_files(located_shares, import_names).items():
        _backup_config_file(source_path)
        source_path.write_text(content, encoding="utf-8")

    names = ", ".join(share.name for share in importable)
    _log(f"Importiert: {names} (Basis: {new_base})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
