"""Samba-Operationen über Unix-Socket an den Root-Daemon (kein sudo)."""

from __future__ import annotations

import configparser
import json
import re
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Any

from app.validators import ValidationError, validate_comment, validate_share_name, validate_share_path

PRIV_SOCKET = "/run/simple-samba-ui/priv.sock"
SOCKET_TIMEOUT = 120
PRIV_SOCKET_RETRIES = 5
PRIV_SOCKET_RETRY_DELAY = 0.4


class SambaError(Exception):
    """Fehler bei Samba-Operationen."""


@dataclass
class Share:
    name: str
    path: str
    comment: str = ""
    browseable: bool = True
    read_only: bool = False
    guest_ok: bool = False
    valid_users: list[str] = field(default_factory=list)
    enabled: bool = True
    create_mask: str = "0660"
    directory_mask: str = "0770"

    def to_ini_section(self) -> str:
        lines = [f"[{self.name}]"]
        if not self.enabled:
            lines.append("available = no")
        lines.append(f"path = {self.path}")
        if self.comment:
            lines.append(f"comment = {self.comment}")
        lines.append(f"browseable = {'yes' if self.browseable else 'no'}")
        lines.append(f"read only = {'yes' if self.read_only else 'no'}")
        lines.append(f"guest ok = {'yes' if self.guest_ok else 'no'}")
        if self.valid_users and not self.guest_ok:
            lines.append(f"valid users = {' '.join(self.valid_users)}")
        lines.append(f"create mask = {self.create_mask}")
        lines.append(f"directory mask = {self.directory_mask}")
        return "\n".join(lines)


def _priv_request(
    command: str,
    body: str = "",
    arg: str = "",
    timeout: int | None = None,
) -> tuple[bool, str]:
    """Sendet Anfrage an den Privilege-Daemon (mit kurzem Retry bei Neustart)."""
    import time

    header = command if not arg else f"{command} {arg}"
    payload = f"{header}\n{body}".encode("utf-8")
    last_error: Exception | None = None
    sock_timeout = timeout if timeout is not None else SOCKET_TIMEOUT

    for attempt in range(PRIV_SOCKET_RETRIES):
        chunks: list[bytes] = []
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(sock_timeout)
                sock.connect(PRIV_SOCKET)
                sock.sendall(payload)
                sock.shutdown(socket.SHUT_WR)

                while True:
                    data = sock.recv(65536)
                    if not data:
                        break
                    chunks.append(data)
        except FileNotFoundError as exc:
            last_error = exc
            time.sleep(PRIV_SOCKET_RETRY_DELAY)
            continue
        except OSError as exc:
            last_error = exc
            time.sleep(PRIV_SOCKET_RETRY_DELAY)
            continue

        raw = b"".join(chunks).decode("utf-8", errors="replace")
        if raw.strip():
            break
        time.sleep(PRIV_SOCKET_RETRY_DELAY)
    else:
        if isinstance(last_error, FileNotFoundError):
            raise SambaError(
                "Privilege-Daemon nicht erreichbar. "
                "Ist simple-samba-ui-priv.service aktiv?"
            ) from last_error
        if last_error:
            raise SambaError(f"Privilege-Daemon nicht erreichbar: {last_error}") from last_error
        raise SambaError("Leere Antwort vom Privilege-Daemon.")

    lines = raw.split("\n", 1)
    status_line = lines[0].strip()
    output = lines[1].rstrip("\n") if len(lines) > 1 else ""

    if status_line == "OK":
        return True, output
    if status_line.startswith("FAIL "):
        return False, status_line[5:] + ("\n" + output if output else "")
    if status_line == "FAIL":
        return False, output or "Unbekannter Fehler"
    return False, raw


def read_shares(shares_file: str) -> list[Share]:
    try:
        with open(shares_file, encoding="utf-8") as fh:
            content = fh.read()
    except OSError as exc:
        raise SambaError(f"Freigabedatei nicht lesbar: {exc}") from exc

    if not content.strip():
        return []

    parser = configparser.ConfigParser(
        interpolation=None,
        delimiters=("=",),
        comment_prefixes=("#", ";"),
        inline_comment_prefixes=("#", ";"),
    )
    parser.optionxform = str  # type: ignore[method-assign]
    parser.read_string(content)

    shares: list[Share] = []
    for section in parser.sections():
        opts = parser[section]
        available = opts.get("available", "yes").strip().lower()
        valid_users_raw = opts.get("valid users", "").strip()
        users = [u for u in re.split(r"[\s,]+", valid_users_raw) if u]
        shares.append(
            Share(
                name=section,
                path=opts.get("path", "").strip(),
                comment=opts.get("comment", "").strip(),
                browseable=opts.get("browseable", "yes").strip().lower() != "no",
                read_only=opts.get("read only", "no").strip().lower() == "yes",
                guest_ok=opts.get("guest ok", "no").strip().lower() == "yes",
                valid_users=users,
                enabled=available != "no",
                create_mask=opts.get("create mask", "0660").strip(),
                directory_mask=opts.get("directory mask", "0770").strip(),
            )
        )
    return shares


def shares_to_config_content(shares: list[Share]) -> str:
    if not shares:
        return (
            "# Verwaltet von Simple Samba UI\n"
            "# Keine Freigaben definiert.\n"
        )
    blocks = ["# Verwaltet von Simple Samba UI – nicht manuell bearbeiten\n"]
    for share in shares:
        blocks.append(share.to_ini_section())
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"


def write_shares(shares: list[Share], shares_file: str, base_path: str) -> None:
    """Validiert und schreibt Freigaben über den Privilege-Daemon."""
    validated: list[Share] = []
    for share in shares:
        name = validate_share_name(share.name)
        path = validate_share_path(share.path, base_path)
        comment = validate_comment(share.comment)
        validated.append(
            Share(
                name=name,
                path=path,
                comment=comment,
                browseable=share.browseable,
                read_only=share.read_only,
                guest_ok=share.guest_ok,
                valid_users=share.valid_users,
                enabled=share.enabled,
                create_mask=share.create_mask,
                directory_mask=share.directory_mask,
            )
        )

    content = shares_to_config_content(validated)
    ok, detail = _priv_request("write-shares", body=content)
    if not ok:
        raise SambaError(f"Freigaben konnten nicht gespeichert werden: {detail}")


def get_share_by_name(shares: list[Share], name: str) -> Share | None:
    key = name.casefold()
    for share in shares:
        if share.name.casefold() == key:
            return share
    return None


def share_names_equal(left: str, right: str) -> bool:
    return left.casefold() == right.casefold()


def service_status() -> dict[str, Any]:
    ok_active, active = _priv_request("smbd-is-active")
    ok_status, status_out = _priv_request("smbd-status")
    return {
        "active": active if ok_active else "unknown",
        "is_running": ok_active and active == "active",
        "output": status_out if ok_status else active,
        "returncode": 0 if ok_status else 1,
    }


def reload_samba() -> None:
    ok, detail = _priv_request("smbd-reload")
    if not ok:
        raise SambaError(f"smbd reload fehlgeschlagen: {detail}")


def restart_samba() -> None:
    ok, detail = _priv_request("smbd-restart")
    if not ok:
        raise SambaError(f"smbd restart fehlgeschlagen: {detail}")


def run_testparm() -> dict[str, str]:
    ok, output = _priv_request("testparm")
    return {
        "success": ok,
        "output": output.strip(),
        "returncode": "0" if ok else "1",
    }


def list_samba_users() -> list[str]:
    ok, output = _priv_request("pdbedit-list")
    if not ok:
        raise SambaError(f"pdbedit fehlgeschlagen: {output}")
    users = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        username = line.split(":", 1)[0]
        if username:
            users.append(username)
    return sorted(set(users))


def add_samba_user(username: str, password: str) -> None:
    payload = f"{password}\n{password}\n"
    ok, detail = _priv_request("smbpasswd-add", body=payload, arg=username)
    if not ok:
        raise SambaError(f"Benutzer konnte nicht angelegt werden: {detail}")


def set_samba_password(username: str, password: str) -> None:
    payload = f"{password}\n{password}\n"
    ok, detail = _priv_request("smbpasswd-set", body=payload, arg=username)
    if not ok:
        raise SambaError(f"Passwort konnte nicht gesetzt werden: {detail}")


def delete_share_directory(path: str, base_path: str) -> None:
    """Löscht ein Freigabe-Verzeichnis über den Privilege-Daemon."""
    validated = validate_share_path(path, base_path)
    ok, detail = _priv_request("delete-share-path", arg=validated)
    if not ok:
        raise SambaError(f"Verzeichnis konnte nicht gelöscht werden: {detail}")


def delete_samba_user(username: str) -> None:
    ok, detail = _priv_request("pdbedit-delete", arg=username)
    if not ok:
        raise SambaError(f"Benutzer konnte nicht gelöscht werden: {detail}")


def list_importable_shares() -> dict:
    ok, output = _priv_request("list-importable-shares")
    if not ok:
        raise SambaError(output or "Import-Liste nicht verfügbar.")
    return json.loads(output)


def import_shares(names: list[str], *, comment_out_source: bool = True) -> None:
    payload = json.dumps({"names": names, "comment_out_source": comment_out_source})
    ok, detail = _priv_request("import-shares", body=payload)
    if not ok:
        raise SambaError(detail or "Import fehlgeschlagen.")
