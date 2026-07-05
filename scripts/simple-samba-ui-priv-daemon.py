#!/usr/bin/env python3
"""
Simple Samba UI – privilegierter Hintergrund-Daemon (läuft als root).

Kommunikation über Unix-Socket /run/simple-samba-ui/priv.sock
(nur Gruppe samba-ui, kein sudo nötig).
"""

from __future__ import annotations

import grp
import json
import configparser
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

SOCKET_PATH = Path("/run/simple-samba-ui/priv.sock")
CONFIG_PATH = Path("/etc/simple-samba-ui/config.json")
SMB_CONF = Path("/etc/samba/smb.conf")
INSTALL_ROOT = Path("/opt/simple-samba-ui")
ALLOWED_UID_NAME = "samba-ui"
TARGET = Path("/etc/samba/smb-shares.conf")
BACKUP_DIR = Path("/var/backups/simple-samba-ui")
MAX_BACKUPS = 20
MAX_BODY_BYTES = 512_000
FILE_STAGING_DIR = Path("/var/lib/samba-ui/file-staging")
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
USER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$", re.IGNORECASE)

PROTECTED_UNIX_USERS = frozenset({
    "root", "samba-ui", "daemon", "bin", "sys", "sync", "games", "man", "lp",
    "mail", "news", "uuc", "proxy", "www-data", "backup", "list", "irc",
    "gnats", "nobody", "systemd-network", "systemd-resolve", "messagebus",
    "_apt", "sshd", "statd",
})

SYSTEMCTL = "/bin/systemctl"
TESTPARM = "/usr/bin/testparm"
PDBEDIT = "/usr/bin/pdbedit"
SMBPASSWD = "/usr/bin/smbpasswd"
USERADD = "/usr/sbin/useradd"
USERDEL = "/usr/sbin/userdel"
APT_GET = "/usr/bin/apt-get"
APT = "/usr/bin/apt"
APT_TIMEOUT_UPDATE = 600
APT_TIMEOUT_UPGRADE = 1800
APT_TIMEOUT_AUTOREMOVE = 600
REBOOT_REQUIRED_FILE = Path("/var/run/reboot-required")
REBOOT_DELAY_SECONDS = 4
APT_JOB_DIR = Path("/var/lib/samba-ui/apt-job")
APT_JOB_STATUS_FILE = APT_JOB_DIR / "status.json"
APT_JOB_LOG_FILE = APT_JOB_DIR / "output.log"
APP_UPDATE_JOB_DIR = Path("/var/lib/samba-ui/app-update-job")
APP_UPDATE_JOB_STATUS_FILE = APP_UPDATE_JOB_DIR / "status.json"
APP_UPDATE_JOB_LOG_FILE = APP_UPDATE_JOB_DIR / "output.log"
RUN_APP_UPDATE = Path("/opt/simple-samba-ui/scripts/run-app-update.py")
DEFAULT_SOURCE_CLONE_DIR = Path("/usr/local/src/simple-samba")
DEFAULT_GITHUB_REPO = "MarcelRuh/simple-samba"
DEFAULT_GITHUB_BRANCH = "main"
_apt_job_lock = threading.Lock()
_app_update_job_lock = threading.Lock()
PHASE_LABELS = {
    "start": "Wird gestartet …",
    "update": "Paketlisten aktualisieren",
    "upgrade": "Updates installieren",
    "autoremove": "Nicht benötigte Pakete entfernen",
    "reboot": "Neustart vorbereiten",
    "done": "Abgeschlossen",
}
NOLOGIN_SHELLS = {"/usr/sbin/nologin", "/bin/false", "/usr/bin/false"}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def run_cmd(
    cmd: list[str],
    input_data: str | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    return subprocess.run(
        cmd,
        input=input_data,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def load_app_config() -> dict:
    try:
        with CONFIG_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _ensure_app_import_path() -> None:
    root = str(INSTALL_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _shares_file_path() -> Path:
    cfg = load_app_config()
    return Path(cfg.get("samba_shares_file") or "/etc/samba/smb-shares.conf")


def _parsed_to_share(parsed) -> "Share":
    from app.samba import Share

    return Share(
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


def _backup_smb_conf() -> Path | None:
    if not SMB_CONF.is_file():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True, mode=0o750)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUP_DIR / f"smb.conf.{ts}.bak"
    shutil.copy2(SMB_CONF, backup)
    backups = sorted(BACKUP_DIR.glob("smb.conf.*.bak"))
    while len(backups) > MAX_BACKUPS:
        backups.pop(0).unlink(missing_ok=True)
    return backup


def cmd_list_importable_shares() -> tuple[bool, str]:
    _ensure_app_import_path()
    from app.smbconf_parser import (
        filter_importable,
        parse_all_smb_conf_shares,
        repair_smb_conf_include,
    )
    from app.samba import read_shares

    if not SMB_CONF.is_file():
        return True, json.dumps({"importable": [], "error": "smb.conf nicht gefunden."}, ensure_ascii=False)

    try:
        repair_smb_conf_include(SMB_CONF)
        smbconf_shares = parse_all_smb_conf_shares(SMB_CONF)
    except (OSError, configparser.Error) as exc:
        return True, json.dumps({"importable": [], "error": str(exc)}, ensure_ascii=False)

    shares_file = _shares_file_path()
    existing = read_shares(str(shares_file)) if shares_file.is_file() else []
    importable = filter_importable(smbconf_shares, {share.name for share in existing})
    base = str(get_shares_base())

    payload = {
        "importable": [
            {
                **item.to_dict(),
                "within_base": _path_within_base(item.path, base),
            }
            for item in importable
        ],
        "shares_base_path": base,
    }
    return True, json.dumps(payload, ensure_ascii=False)


def _path_within_base(path_str: str, base: str) -> bool:
    try:
        Path(path_str).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


def _update_config_shares_base(paths: list[str]) -> str:
    from app.smbconf_parser import infer_shares_base_path

    cfg = load_app_config()
    current = str(cfg.get("shares_base_path") or "/srv/shares")
    new_base = infer_shares_base_path(paths, default=current)
    if cfg.get("shares_base_path") == new_base:
        return new_base
    cfg["shares_base_path"] = new_base
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(CONFIG_PATH, 0o600)
    try:
        uid = pwd.getpwnam("samba-ui").pw_uid
        gid = pwd.getpwnam("samba-ui").pw_gid
        os.chown(CONFIG_PATH, uid, gid)
    except KeyError:
        pass
    return new_base


def cmd_import_shares(body_text: str) -> tuple[bool, str]:
    _ensure_app_import_path()
    from app.smbconf_parser import (
        comment_out_shares_in_files,
        parse_all_smb_conf_shares_with_sources,
        repair_smb_conf_include,
    )
    from app.samba import Share, read_shares, shares_to_config_content

    try:
        data = json.loads(body_text or "{}")
    except json.JSONDecodeError:
        return False, "Ungültiges JSON."

    names = {str(name).strip() for name in data.get("names", []) if str(name).strip()}
    if not names:
        return False, "Keine Freigaben ausgewählt."
    comment_out = bool(data.get("comment_out_source", True))

    if not SMB_CONF.is_file():
        return False, "smb.conf nicht gefunden."

    repair_smb_conf_include(SMB_CONF)
    located_shares = parse_all_smb_conf_shares_with_sources(SMB_CONF)
    smbconf_shares = [item.share for item in located_shares]
    selected = [share for share in smbconf_shares if share.name in names]
    if len(selected) != len(names):
        missing = names - {share.name for share in selected}
        return False, f"Freigaben nicht in smb.conf gefunden: {', '.join(sorted(missing))}"

    shares_file = _shares_file_path()
    existing = read_shares(str(shares_file)) if shares_file.is_file() else []
    all_paths = [share.path for share in existing] + [share.path for share in selected]
    _update_config_shares_base(all_paths)

    merged: list[Share] = list(existing)
    for parsed in selected:
        if any(share.name.lower() == parsed.name.lower() for share in merged):
            return False, f"Freigabe „{parsed.name}“ existiert bereits in smb-shares.conf."
        merged.append(_parsed_to_share(parsed))

    content = shares_to_config_content(merged)
    smb_conf_backup = None
    source_backups: dict[Path, Path] = {}
    try:
        if comment_out:
            if SMB_CONF.is_file():
                smb_conf_backup = _backup_smb_conf()
            for source_path, updated in comment_out_shares_in_files(located_shares, names).items():
                BACKUP_DIR.mkdir(parents=True, exist_ok=True, mode=0o750)
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup = BACKUP_DIR / f"{source_path.name}.{ts}.bak"
                shutil.copy2(source_path, backup)
                source_backups[source_path] = backup
                source_path.write_text(updated, encoding="utf-8")

        return cmd_write_shares(content)
    except OSError as exc:
        if smb_conf_backup and smb_conf_backup.is_file():
            shutil.copy2(smb_conf_backup, SMB_CONF)
        for source_path, backup in source_backups.items():
            if backup.is_file():
                shutil.copy2(backup, source_path)
        return False, f"Import fehlgeschlagen: {exc}"


def get_shares_base() -> Path:
    cfg = load_app_config()
    base = cfg.get("shares_base_path") or os.environ.get("SAMBA_UI_SHARES_BASE", "/srv/shares")
    return Path(base).resolve()


def validate_username(username: str) -> str:
    username = (username or "").strip().lower()
    if not USER_RE.match(username):
        raise ValueError(f"Ungültiger Benutzername: {username!r}")
    if username in PROTECTED_UNIX_USERS:
        raise ValueError(f"Benutzername {username!r} ist reserviert.")
    return username


def unix_user_exists(username: str) -> bool:
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def ensure_unix_user(username: str) -> tuple[bool, str]:
    """Legt Linux-Systembenutzer an, falls smbpasswd ihn benötigt (ohne Home-Verzeichnis)."""
    if unix_user_exists(username):
        return True, "Linux-Benutzer existiert bereits."

    result = run_cmd([
        USERADD,
        "--no-create-home",
        "--home-dir", "/nonexistent",
        "--shell", "/usr/sbin/nologin",
        username,
    ])
    if result.returncode != 0:
        detail = ((result.stderr or "") + (result.stdout or "")).strip()
        return False, f"Linux-Benutzer konnte nicht angelegt werden: {detail}"

    return True, f"Linux-Benutzer {username} angelegt (ohne Home-Verzeichnis)."


def remove_unix_user_if_safe(username: str) -> None:
    if username in PROTECTED_UNIX_USERS:
        return
    try:
        pw = pwd.getpwnam(username)
    except KeyError:
        return
    if pw.pw_uid < 1000:
        return
    if pw.pw_shell not in NOLOGIN_SHELLS:
        return
    run_cmd([USERDEL, "--remove", username])


def parse_share_sections(content: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            if current:
                sections.append(current)
            current = {"__name__": stripped[1:-1]}
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            current[key.strip().lower()] = value.strip()
    if current:
        sections.append(current)
    return sections


def ensure_share_directories(content: str) -> tuple[bool, str]:
    """Erstellt Freigabe-Verzeichnisse; Rechte nur best-effort (ZFS-Mounts)."""
    errors: list[str] = []
    warnings: list[str] = []
    for section in parse_share_sections(content):
        path_str = section.get("path")
        if not path_str:
            continue
        p = Path(path_str)
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            errors.append(f"{path_str}: Verzeichnis konnte nicht erstellt werden: {exc}")
            continue

        guest_ok = section.get("guest ok", "no").lower() == "yes"
        valid_raw = section.get("valid users", "")
        valid_users = [u for u in re.split(r"[\s,]+", valid_raw) if u]

        try:
            if not guest_ok and len(valid_users) == 1:
                pw = pwd.getpwnam(valid_users[0])
                os.chown(p, pw.pw_uid, pw.pw_gid)
                os.chmod(p, 0o2770)
            elif guest_ok:
                os.chmod(p, 0o2777)
            else:
                os.chmod(p, 0o2770)
        except (OSError, KeyError) as exc:
            warnings.append(
                f"{path_str}: Rechte nicht änderbar ({exc}) – bei ZFS-Mount ggf. am Host setzen."
            )

    if errors:
        return False, "Verzeichnisse konnten nicht vorbereitet werden:\n" + "\n".join(errors)
    msg = "Verzeichnisse bereit."
    if warnings:
        msg += "\n" + "\n".join(warnings)
    return True, msg


def extract_share_paths(content: str) -> list[str]:
    return [s["path"] for s in parse_share_sections(content) if s.get("path")]


def validate_share_content(content: str) -> None:
    if not content.endswith("\n"):
        raise ValueError("Inhalt muss mit Newline enden.")
    if "\0" in content:
        raise ValueError("Inhalt enthält Null-Bytes.")

    base = get_shares_base()
    for path_str in extract_share_paths(content):
        if not path_str.startswith("/"):
            raise ValueError(f"Ungültiger Pfad (nicht absolut): {path_str}")
        if ".." in path_str.split("/"):
            raise ValueError(f"Pfad darf keine .. enthalten: {path_str}")
        resolved = Path(path_str).resolve()
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"Pfad {path_str} liegt nicht unter {base}") from exc


def validate_share_path_str(path_str: str) -> Path:
    """Einzelnen Freigabe-Pfad validieren (muss unter Basisverzeichnis liegen)."""
    path_str = (path_str or "").strip()
    if not path_str.startswith("/"):
        raise ValueError(f"Ungültiger Pfad (nicht absolut): {path_str}")
    if ".." in path_str.split("/"):
        raise ValueError(f"Pfad darf keine .. enthalten: {path_str}")
    base = get_shares_base()
    resolved = Path(path_str).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Pfad {path_str} liegt nicht unter {base}") from exc
    if resolved == base:
        raise ValueError("Das Basisverzeichnis selbst darf nicht gelöscht werden.")
    return resolved


def cmd_delete_share_path(path_str: str) -> tuple[bool, str]:
    try:
        resolved = validate_share_path_str(path_str)
    except ValueError as exc:
        return False, str(exc)

    if not resolved.exists():
        return True, "Verzeichnis war bereits entfernt."

    if not resolved.is_dir():
        return False, f"Pfad ist kein Verzeichnis: {resolved}"

    try:
        shutil.rmtree(resolved)
    except OSError as exc:
        return False, f"Verzeichnis konnte nicht gelöscht werden: {exc}"

    return True, f"Verzeichnis gelöscht: {resolved}"


def _ensure_file_staging_dir() -> None:
    FILE_STAGING_DIR.mkdir(parents=True, exist_ok=True, mode=0o770)
    try:
        gid = grp.getgrnam("samba-ui").gr_gid
        os.chown(FILE_STAGING_DIR, 0, gid)
    except KeyError:
        pass


def _get_enabled_share_paths() -> list[Path]:
    _ensure_app_import_path()
    from app.samba import read_shares

    cfg = load_app_config()
    shares_file = cfg.get("samba_shares_file") or "/etc/samba/smb-shares.conf"
    try:
        shares = read_shares(str(shares_file))
    except Exception:
        return []
    roots: list[Path] = []
    for share in shares:
        if not share.enabled or not share.path:
            continue
        roots.append(Path(share.path).resolve())
    return roots


def validate_browser_path(path_str: str) -> Path:
    """Pfad muss unter Basisverzeichnis und unter einer aktiven Freigabe liegen."""
    resolved = validate_share_path_str(path_str)
    roots = _get_enabled_share_paths()
    if not roots:
        raise ValueError("Keine aktiven Freigaben konfiguriert.")
    for root in roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ValueError("Pfad liegt nicht unter einer Freigabe.")


def _is_share_root(path: Path) -> bool:
    return path.resolve() in _get_enabled_share_paths()


def cmd_files_list(path_str: str) -> tuple[bool, str]:
    try:
        directory = validate_browser_path(path_str)
    except ValueError as exc:
        return False, str(exc)

    if not directory.is_dir():
        return False, "Pfad ist kein Verzeichnis."

    entries: list[dict] = []
    try:
        with os.scandir(directory) as scan:
            for entry in sorted(scan, key=lambda item: (not item.is_dir(), item.name.lower())):
                if entry.name.startswith("."):
                    continue
                info = entry.stat(follow_symlinks=False)
                entries.append({
                    "name": entry.name,
                    "type": "dir" if entry.is_dir(follow_symlinks=False) else "file",
                    "size": info.st_size,
                    "mtime": int(info.st_mtime),
                })
    except OSError as exc:
        return False, f"Verzeichnis nicht lesbar: {exc}"

    payload = {
        "path": str(directory),
        "entries": entries,
    }
    return True, json.dumps(payload, ensure_ascii=False)


def cmd_files_mkdir(path_str: str) -> tuple[bool, str]:
    try:
        target = validate_browser_path(path_str)
    except ValueError as exc:
        return False, str(exc)

    try:
        target.mkdir(parents=False, exist_ok=False)
        os.chmod(target, 0o2770)
    except FileExistsError:
        return False, "Ordner existiert bereits."
    except OSError as exc:
        return False, f"Ordner konnte nicht erstellt werden: {exc}"
    return True, f"Ordner erstellt: {target}"


def cmd_files_delete(path_str: str) -> tuple[bool, str]:
    try:
        target = validate_browser_path(path_str)
    except ValueError as exc:
        return False, str(exc)

    if _is_share_root(target):
        return False, "Freigabe-Wurzelverzeichnis kann nicht gelöscht werden."

    try:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
        else:
            return False, "Pfad nicht gefunden."
    except OSError as exc:
        return False, f"Löschen fehlgeschlagen: {exc}"
    return True, "Gelöscht."


def cmd_files_stage_download(path_str: str) -> tuple[bool, str]:
    try:
        source = validate_browser_path(path_str)
    except ValueError as exc:
        return False, str(exc)

    _ensure_file_staging_dir()
    token = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    try:
        if source.is_file():
            download_name = source.name
            staging = FILE_STAGING_DIR / f"dl-{token}-{download_name}"
            shutil.copy2(source, staging)
        elif source.is_dir():
            download_name = f"{source.name}.zip"
            staging = FILE_STAGING_DIR / f"dl-{token}-{download_name}"
            with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as archive:
                for root, _dirs, files in os.walk(source):
                    for filename in files:
                        if filename.startswith("."):
                            continue
                        full_path = Path(root) / filename
                        archive.write(full_path, full_path.relative_to(source).as_posix())
        else:
            return False, "Pfad nicht gefunden."
        os.chmod(staging, 0o640)
        uid = pwd.getpwnam("samba-ui").pw_uid
        gid = pwd.getpwnam("samba-ui").pw_gid
        os.chown(staging, uid, gid)
    except OSError as exc:
        return False, f"Download konnte nicht vorbereitet werden: {exc}"

    payload = {
        "staging": str(staging),
        "name": download_name,
        "size": staging.stat().st_size,
    }
    return True, json.dumps(payload, ensure_ascii=False)

def cmd_files_commit_upload(body_text: str) -> tuple[bool, str]:
    try:
        data = json.loads(body_text or "{}")
    except json.JSONDecodeError:
        return False, "Ungültiges JSON."

    parent_str = str(data.get("parent", "")).strip()
    staging_str = str(data.get("staging", "")).strip()
    if not parent_str or not staging_str:
        return False, "parent und staging erforderlich."

    try:
        parent = validate_browser_path(parent_str)
    except ValueError as exc:
        return False, str(exc)

    staging = Path(staging_str).resolve()
    staging_root = FILE_STAGING_DIR.resolve()
    try:
        staging.relative_to(staging_root)
    except ValueError:
        return False, "Ungültiger Staging-Pfad."

    if not staging.is_file():
        return False, "Upload-Datei nicht gefunden."

    if not parent.is_dir():
        return False, "Zielverzeichnis existiert nicht."

    dest = parent / staging.name
    if dest.exists():
        return False, f"Datei existiert bereits: {dest.name}"

    try:
        shutil.move(str(staging), dest)
        os.chmod(dest, 0o0660)
    except OSError as exc:
        return False, f"Upload fehlgeschlagen: {exc}"
    return True, f"Datei hochgeladen: {dest.name}"


def create_backup() -> Path | None:
    if not TARGET.is_file():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True, mode=0o750)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUP_DIR / f"smb-shares.conf.{ts}.bak"
    shutil.copy2(TARGET, backup)
    backups = sorted(BACKUP_DIR.glob("smb-shares.conf.*.bak"))
    while len(backups) > MAX_BACKUPS:
        backups.pop(0).unlink(missing_ok=True)
    return backup


def restore_backup(backup: Path | None) -> None:
    if backup and backup.is_file():
        shutil.copy2(backup, TARGET)
    elif not TARGET.is_file():
        TARGET.write_text(
            "# Verwaltet von Simple Samba UI\n# Keine Freigaben definiert.\n",
            encoding="utf-8",
        )


def atomic_write(content: str) -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".smb-shares.", suffix=".tmp", dir=str(TARGET.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, TARGET)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise


def apply_samba_after_config_change() -> tuple[bool, str]:
    """Neue/geänderte Freigaben: smbd + nmbd neu starten (reload reicht oft nicht)."""
    results: list[str] = []
    for unit in ("smbd", "nmbd"):
        result = run_cmd([SYSTEMCTL, "restart", unit])
        detail = ((result.stderr or "") + (result.stdout or "")).strip()
        if result.returncode != 0:
            return False, f"{unit} restart fehlgeschlagen.\n{detail}"
        results.append(f"{unit} neu gestartet")
    return True, ", ".join(results)


def cmd_write_shares(body: str) -> tuple[bool, str]:
    try:
        validate_share_content(body)
    except ValueError as exc:
        return False, str(exc)

    ok_dirs, dir_msg = ensure_share_directories(body)
    if not ok_dirs:
        return False, dir_msg

    backup = create_backup()
    try:
        atomic_write(body)
    except OSError as exc:
        restore_backup(backup)
        return False, f"Schreiben fehlgeschlagen: {exc}"

    result = run_cmd([TESTPARM, "-s"])
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        restore_backup(backup)
        return False, f"Konfigurationsprüfung fehlgeschlagen – Rollback.\n{stdout}\n{stderr}".strip()

    ok_apply, apply_msg = apply_samba_after_config_change()
    if not ok_apply:
        return False, f"Konfiguration gespeichert, aber Dienst-Neustart fehlgeschlagen.\n{apply_msg}"

    return True, f"Freigaben gespeichert und Samba neu gestartet. {dir_msg}"


def cmd_smbd_is_active() -> tuple[bool, str]:
    result = run_cmd([SYSTEMCTL, "is-active", "smbd"])
    return result.returncode == 0, (result.stdout or result.stderr or "").strip()


def cmd_smbd_status() -> tuple[bool, str]:
    result = run_cmd([SYSTEMCTL, "status", "smbd", "--no-pager", "-l"])
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return True, output


def cmd_smbd_reload() -> tuple[bool, str]:
    """Reload – für manuelle Aktion; Freigabe-Änderungen nutzen restart."""
    result = run_cmd([SYSTEMCTL, "reload", "smbd"])
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode == 0, output or "smbd reload OK"


def cmd_smbd_restart() -> tuple[bool, str]:
    ok, msg = apply_samba_after_config_change()
    return ok, msg or "Samba neu gestartet"


def cmd_testparm() -> tuple[bool, str]:
    result = run_cmd([TESTPARM, "-s"])
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode == 0:
        return True, stdout or stderr
    return False, f"{stdout}\n{stderr}".strip()


def cmd_pdbedit_list() -> tuple[bool, str]:
    result = run_cmd([PDBEDIT, "-L"])
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode == 0, output


def cmd_pdbedit_delete(username: str) -> tuple[bool, str]:
    try:
        user = validate_username(username)
    except ValueError as exc:
        return False, str(exc)

    result = run_cmd([PDBEDIT, "-x", user])
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode != 0:
        return False, output or "Samba-Benutzer konnte nicht gelöscht werden."

    remove_unix_user_if_safe(user)
    return True, output or f"Benutzer {user} gelöscht."


def cmd_smbpasswd_add(username: str, body: str) -> tuple[bool, str]:
    try:
        user = validate_username(username)
    except ValueError as exc:
        return False, str(exc)

    ok_user, user_msg = ensure_unix_user(user)
    if not ok_user:
        return False, user_msg

    if not body.endswith("\n"):
        body = body + "\n"
    result = run_cmd([SMBPASSWD, "-a", "-s", user], input_data=body)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode != 0:
        return False, output or "Samba-Passwort konnte nicht gesetzt werden."
    return True, f"{user_msg}\n{output}".strip()


def cmd_smbpasswd_set(username: str, body: str) -> tuple[bool, str]:
    try:
        user = validate_username(username)
    except ValueError as exc:
        return False, str(exc)
    if not unix_user_exists(user):
        return False, (
            f"Linux-Benutzer {user!r} existiert nicht. "
            "Bitte Benutzer neu anlegen oder Systembenutzer manuell erstellen."
        )
    if not body.endswith("\n"):
        body = body + "\n"
    result = run_cmd([SMBPASSWD, "-s", user], input_data=body)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode == 0, output


def _apt_missing_msg() -> str:
    return "apt-get nicht gefunden. Nur auf Debian/Ubuntu-Systemen verfügbar."


def _format_apt_output(result: subprocess.CompletedProcess[str]) -> str:
    parts = []
    if result.stdout and result.stdout.strip():
        parts.append(result.stdout.strip())
    if result.stderr and result.stderr.strip():
        parts.append(result.stderr.strip())
    return "\n".join(parts).strip() or "(keine Ausgabe)"


def cmd_apt_update() -> tuple[bool, str]:
    if not Path(APT_GET).is_file():
        return False, _apt_missing_msg()
    result = run_cmd([APT_GET, "update"], timeout=APT_TIMEOUT_UPDATE)
    output = _format_apt_output(result)
    if result.returncode != 0:
        return False, f"apt update fehlgeschlagen.\n{output}"
    return True, f"Paketlisten aktualisiert.\n{output}"


def cmd_apt_upgradable() -> tuple[bool, str]:
    if not Path(APT).is_file():
        return False, _apt_missing_msg()
    result = run_cmd([APT, "list", "--upgradable"], timeout=120)
    output = _format_apt_output(result)
    if result.returncode != 0:
        return False, f"Update-Prüfung fehlgeschlagen.\n{output}"

    packages: list[str] = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line or line.startswith("Listing"):
            continue
        pkg = line.split("/", 1)[0].strip()
        if pkg:
            packages.append(pkg)

    if packages:
        return True, "\n".join(packages)
    return True, ""


def _reboot_required() -> bool:
    return REBOOT_REQUIRED_FILE.is_file()


def _reboot_required_reason() -> str:
    if not REBOOT_REQUIRED_FILE.is_file():
        return ""
    try:
        return REBOOT_REQUIRED_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "Kernel- oder Systemupdate erfordert Neustart."


def _schedule_system_reboot() -> None:
    def _reboot() -> None:
        time.sleep(REBOOT_DELAY_SECONDS)
        run_cmd([SYSTEMCTL, "reboot"], timeout=30)

    threading.Thread(target=_reboot, daemon=True).start()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chown_job_files() -> None:
    gid = grp.getgrnam(ALLOWED_UID_NAME).gr_gid
    for path in (APT_JOB_DIR, APT_JOB_STATUS_FILE, APT_JOB_LOG_FILE):
        if path.exists():
            os.chown(path, 0, gid)
    if APT_JOB_DIR.is_dir():
        os.chmod(APT_JOB_DIR, 0o750)
    if APT_JOB_STATUS_FILE.is_file():
        os.chmod(APT_JOB_STATUS_FILE, 0o660)
    if APT_JOB_LOG_FILE.is_file():
        os.chmod(APT_JOB_LOG_FILE, 0o660)


def _read_job_status() -> dict:
    if not APT_JOB_STATUS_FILE.is_file():
        return {"status": "idle"}
    try:
        return json.loads(APT_JOB_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "idle"}


def _write_job_status(data: dict) -> None:
    APT_JOB_DIR.mkdir(parents=True, exist_ok=True)
    APT_JOB_STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _chown_job_files()


def _read_job_log() -> str:
    if not APT_JOB_LOG_FILE.is_file():
        return ""
    try:
        return APT_JOB_LOG_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def _append_job_log(text: str) -> None:
    APT_JOB_DIR.mkdir(parents=True, exist_ok=True)
    with APT_JOB_LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(text)
        if not text.endswith("\n"):
            fh.write("\n")
    _chown_job_files()


def _set_job_phase(phase: str, status: str = "running") -> None:
    current = _read_job_status()
    current.update({
        "status": status,
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
    })
    _write_job_status(current)


def _run_apt_upgrade_core(*, track_job: bool) -> tuple[bool, str, bool]:
    """apt update, upgrade, autoremove. Returns success, summary, reboot_pending."""
    if not Path(APT_GET).is_file():
        return False, _apt_missing_msg(), False

    sections: list[str] = []

    if track_job:
        _set_job_phase("update")
    update = run_cmd([APT_GET, "update"], timeout=APT_TIMEOUT_UPDATE)
    block = f"=== apt update ===\n{_format_apt_output(update)}"
    sections.append(block)
    if track_job:
        _append_job_log(block)
    if update.returncode != 0:
        return False, "apt update fehlgeschlagen.\n\n" + block, False

    if track_job:
        _set_job_phase("upgrade")
    upgrade = run_cmd(
        [
            APT_GET,
            "-y",
            "-o", "Dpkg::Options::=--force-confdef",
            "-o", "Dpkg::Options::=--force-confold",
            "upgrade",
        ],
        timeout=APT_TIMEOUT_UPGRADE,
    )
    block = f"=== apt upgrade ===\n{_format_apt_output(upgrade)}"
    sections.append(block)
    if track_job:
        _append_job_log(block)
    if upgrade.returncode != 0:
        return False, "apt upgrade fehlgeschlagen.\n\n" + "\n\n".join(sections), False

    if track_job:
        _set_job_phase("autoremove")
    autoremove = run_cmd([APT_GET, "-y", "autoremove"], timeout=APT_TIMEOUT_AUTOREMOVE)
    block = f"=== apt autoremove ===\n{_format_apt_output(autoremove)}"
    sections.append(block)
    if track_job:
        _append_job_log(block)
    if autoremove.returncode != 0:
        return False, "apt autoremove fehlgeschlagen.\n\n" + "\n\n".join(sections), False

    msg = "Updates installiert.\n\n" + "\n\n".join(sections)
    reboot_pending = _reboot_required()
    if reboot_pending:
        reason = _reboot_required_reason()
        if track_job:
            _set_job_phase("reboot")
        reboot_msg = "\n\n=== Neustart ===\nNeustart erforderlich"
        if reason:
            reboot_msg += f": {reason}"
        reboot_msg += f"\nSystem startet in ca. {REBOOT_DELAY_SECONDS} Sekunden neu."
        msg += reboot_msg
        if track_job:
            _append_job_log(reboot_msg)
        _schedule_system_reboot()

    return True, msg, reboot_pending


def _apt_upgrade_worker() -> None:
    started = _iso_now()
    try:
        APT_JOB_DIR.mkdir(parents=True, exist_ok=True)
        APT_JOB_LOG_FILE.write_text("", encoding="utf-8")
        _chown_job_files()
        _write_job_status({
            "status": "running",
            "phase": "start",
            "phase_label": PHASE_LABELS["start"],
            "success": None,
            "started_at": started,
            "finished_at": None,
            "reboot_pending": False,
        })
        ok, _, reboot_pending = _run_apt_upgrade_core(track_job=True)
        finished = _iso_now()
        _write_job_status({
            "status": "done" if ok else "failed",
            "phase": "done",
            "phase_label": PHASE_LABELS["done"],
            "success": ok,
            "started_at": started,
            "finished_at": finished,
            "reboot_pending": reboot_pending and ok,
        })
    except Exception as exc:
        log(f"apt-job Fehler: {exc}")
        _append_job_log(f"Interner Fehler: {exc}")
        _write_job_status({
            "status": "failed",
            "phase": "done",
            "phase_label": PHASE_LABELS["done"],
            "success": False,
            "started_at": started,
            "finished_at": _iso_now(),
            "reboot_pending": False,
        })


def cmd_apt_upgrade_start() -> tuple[bool, str]:
    with _apt_job_lock:
        if _any_update_job_running():
            return False, "Eine Update-Installation läuft bereits."
        thread = threading.Thread(target=_apt_upgrade_worker, daemon=True)
        thread.start()
    return True, "running"


def cmd_apt_job_status() -> tuple[bool, str]:
    data = _read_job_status()
    data["output"] = _read_job_log()
    return True, json.dumps(data, ensure_ascii=False)


def _github_settings() -> tuple[Path, str, str]:
    cfg = load_app_config()
    clone_dir = Path(cfg.get("source_clone_dir") or DEFAULT_SOURCE_CLONE_DIR)
    repo = str(cfg.get("github_repo") or DEFAULT_GITHUB_REPO).strip("/")
    branch = str(cfg.get("github_branch") or DEFAULT_GITHUB_BRANCH).strip()
    return clone_dir, repo, branch


def _chown_app_update_job_files() -> None:
    gid = grp.getgrnam(ALLOWED_UID_NAME).gr_gid
    for path in (APP_UPDATE_JOB_DIR, APP_UPDATE_JOB_STATUS_FILE, APP_UPDATE_JOB_LOG_FILE):
        if path.exists():
            os.chown(path, 0, gid)
    if APP_UPDATE_JOB_DIR.is_dir():
        os.chmod(APP_UPDATE_JOB_DIR, 0o750)
    if APP_UPDATE_JOB_STATUS_FILE.is_file():
        os.chmod(APP_UPDATE_JOB_STATUS_FILE, 0o660)
    if APP_UPDATE_JOB_LOG_FILE.is_file():
        os.chmod(APP_UPDATE_JOB_LOG_FILE, 0o660)


def _app_update_worker_alive() -> bool:
    result = run_cmd(["pgrep", "-f", "scripts/run-app-update.py"], timeout=5)
    return result.returncode == 0


def _write_app_update_job_status(data: dict) -> None:
    APP_UPDATE_JOB_DIR.mkdir(parents=True, exist_ok=True)
    APP_UPDATE_JOB_STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _chown_app_update_job_files()


def _cleanup_stale_app_update_job(data: dict) -> dict:
    if data.get("status") != "running":
        return data
    if _app_update_worker_alive():
        return data
    stale = {
        **data,
        "status": "failed",
        "phase": "done",
        "phase_label": "Abgebrochen",
        "success": False,
        "finished_at": _iso_now(),
    }
    _write_app_update_job_status(stale)
    _append_app_update_job_log("Update-Prozess nicht mehr aktiv – Job als abgebrochen markiert.")
    return stale


def _append_app_update_job_log(text: str) -> None:
    APP_UPDATE_JOB_DIR.mkdir(parents=True, exist_ok=True)
    with APP_UPDATE_JOB_LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(text.rstrip("\n") + "\n")
    _chown_app_update_job_files()


def _read_app_update_job_status() -> dict:
    if not APP_UPDATE_JOB_STATUS_FILE.is_file():
        return {"status": "idle"}
    try:
        data = json.loads(APP_UPDATE_JOB_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "idle"}
    return _cleanup_stale_app_update_job(data)


def _read_app_update_job_log() -> str:
    if not APP_UPDATE_JOB_LOG_FILE.is_file():
        return ""
    try:
        return APP_UPDATE_JOB_LOG_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def _any_update_job_running() -> bool:
    apt = _read_job_status().get("status")
    app = _read_app_update_job_status().get("status")
    return apt == "running" or app == "running"


def cmd_app_update_start() -> tuple[bool, str]:
    with _app_update_job_lock:
        if _any_update_job_running():
            return False, "Eine Update-Installation läuft bereits."
        clone_dir, repo, branch = _github_settings()
        script = RUN_APP_UPDATE if RUN_APP_UPDATE.is_file() else Path(__file__).with_name("run-app-update.py")
        if not script.is_file():
            return False, "Update-Script nicht gefunden. Bitte App manuell aktualisieren."
        APP_UPDATE_JOB_DIR.mkdir(parents=True, exist_ok=True)
        APP_UPDATE_JOB_LOG_FILE.write_text("", encoding="utf-8")
        started = _iso_now()
        APP_UPDATE_JOB_STATUS_FILE.write_text(
            json.dumps({
                "status": "running",
                "phase": "start",
                "phase_label": "Wird gestartet …",
                "success": None,
                "started_at": started,
                "finished_at": None,
                "new_version": None,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        _chown_app_update_job_files()
        subprocess.Popen(
            [sys.executable, str(script), str(clone_dir), repo, branch],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return True, "running"


def cmd_app_update_status() -> tuple[bool, str]:
    data = _read_app_update_job_status()
    data["output"] = _read_app_update_job_log()
    return True, json.dumps(data, ensure_ascii=False)


def cmd_system_overview() -> tuple[bool, str]:
    base = get_shares_base()
    disk_error = ""
    disk_total = disk_used = disk_free = 0
    disk_percent = 0.0
    try:
        usage = shutil.disk_usage(base)
        disk_total = usage.total
        disk_used = usage.used
        disk_free = usage.free
        disk_percent = round(usage.used / usage.total * 100, 1) if usage.total else 0.0
    except OSError as exc:
        disk_error = str(exc)

    uptime_seconds = 0
    try:
        uptime_seconds = int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, IndexError, ValueError):
        pass

    reboot = _reboot_required()
    payload = {
        "disk_path": str(base),
        "disk_total": disk_total,
        "disk_used": disk_used,
        "disk_free": disk_free,
        "disk_percent": disk_percent,
        "disk_error": disk_error,
        "reboot_required": reboot,
        "reboot_reason": _reboot_required_reason() if reboot else "",
        "uptime_seconds": uptime_seconds,
    }
    return True, json.dumps(payload, ensure_ascii=False)


def cmd_apt_upgrade() -> tuple[bool, str]:
    """Synchron (Legacy) – bevorzugt apt-upgrade-start nutzen."""
    ok, msg, _reboot = _run_apt_upgrade_core(track_job=False)
    return ok, msg


def handle_request(line: str, body: bytes) -> tuple[bool, str]:
    parts = line.strip().split(maxsplit=1)
    if not parts:
        return False, "Leerer Befehl"
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    try:
        body_text = body.decode("utf-8")
    except UnicodeDecodeError:
        return False, "Body ist kein gültiges UTF-8"

    if len(body) > MAX_BODY_BYTES:
        return False, "Body zu groß"

    handlers = {
        "write-shares": lambda: cmd_write_shares(body_text),
        "smbd-is-active": lambda: cmd_smbd_is_active(),
        "smbd-status": lambda: cmd_smbd_status(),
        "smbd-reload": lambda: cmd_smbd_reload(),
        "smbd-restart": lambda: cmd_smbd_restart(),
        "testparm": lambda: cmd_testparm(),
        "pdbedit-list": lambda: cmd_pdbedit_list(),
        "pdbedit-delete": lambda: cmd_pdbedit_delete(arg),
        "smbpasswd-add": lambda: cmd_smbpasswd_add(arg, body_text),
        "smbpasswd-set": lambda: cmd_smbpasswd_set(arg, body_text),
        "delete-share-path": lambda: cmd_delete_share_path(arg),
        "apt-update": lambda: cmd_apt_update(),
        "apt-upgradable": lambda: cmd_apt_upgradable(),
        "apt-upgrade": lambda: cmd_apt_upgrade(),
        "apt-upgrade-start": lambda: cmd_apt_upgrade_start(),
        "apt-job-status": lambda: cmd_apt_job_status(),
        "app-update-start": lambda: cmd_app_update_start(),
        "app-update-status": lambda: cmd_app_update_status(),
        "list-importable-shares": lambda: cmd_list_importable_shares(),
        "import-shares": lambda: cmd_import_shares(body_text),
        "system-overview": lambda: cmd_system_overview(),
        "files-list": lambda: cmd_files_list(arg),
        "files-mkdir": lambda: cmd_files_mkdir(arg),
        "files-delete": lambda: cmd_files_delete(arg),
        "files-stage-download": lambda: cmd_files_stage_download(arg),
        "files-commit-upload": lambda: cmd_files_commit_upload(body_text),
    }

    handler = handlers.get(command)
    if not handler:
        return False, f"Unbekannter Befehl: {command}"
    return handler()


def handle_client(conn: socket.socket) -> None:
    try:
        chunks: list[bytes] = []
        while True:
            data = conn.recv(65536)
            if not data:
                break
            chunks.append(data)
            if sum(len(c) for c in chunks) > MAX_BODY_BYTES + 1024:
                conn.sendall(b"FAIL Eingabe zu gross\n")
                return

        raw = b"".join(chunks)
        if not raw:
            conn.sendall(b"FAIL Leere Anfrage\n")
            return

        if b"\n" not in raw:
            conn.sendall(b"FAIL Ungueltiges Protokoll\n")
            return

        line_bytes, body = raw.split(b"\n", 1)
        try:
            line = line_bytes.decode("utf-8")
        except UnicodeDecodeError:
            conn.sendall(b"FAIL Ungueltige Kodierung\n")
            return

        ok, output = handle_request(line, body)
        status = "OK" if ok else "FAIL"
        if not ok and output and not output.startswith("FAIL"):
            response = f"{status} {output.splitlines()[0]}\n{output}\n"
        elif ok:
            response = f"OK\n{output}\n"
        else:
            response = f"FAIL\n{output}\n"
        conn.sendall(response.encode("utf-8"))
    except Exception as exc:
        log(f"Client-Fehler: {exc}")
        try:
            conn.sendall(f"FAIL Interner Fehler: {exc}\n".encode("utf-8"))
        except OSError:
            pass


def verify_runtime() -> None:
    if os.geteuid() != 0:
        log("Daemon muss als root laufen.")
        sys.exit(1)
    try:
        grp.getgrnam(ALLOWED_UID_NAME)
        pwd.getpwnam(ALLOWED_UID_NAME)
    except KeyError:
        log(f"Benutzer/Gruppe {ALLOWED_UID_NAME} fehlt.")
        sys.exit(1)


def main() -> None:
    verify_runtime()
    log(f"Basisverzeichnis Freigaben: {get_shares_base()}")

    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SOCKET_PATH))

    gid = grp.getgrnam(ALLOWED_UID_NAME).gr_gid
    os.chown(SOCKET_PATH.parent, 0, gid)
    os.chmod(SOCKET_PATH.parent, 0o750)
    os.chown(SOCKET_PATH, 0, gid)
    os.chmod(SOCKET_PATH, 0o660)

    server.listen(8)
    log(f"Privilege-Daemon bereit auf {SOCKET_PATH}")

    try:
        while True:
            conn, _ = server.accept()
            try:
                handle_client(conn)
            finally:
                conn.close()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        SOCKET_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
