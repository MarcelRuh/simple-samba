"""Eingabevalidierung – keine Shell-Injection, Pfad- und Namensprüfung."""

from __future__ import annotations

import re
from pathlib import Path

SHARE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\- ]+$")
SAMBA_USER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$", re.IGNORECASE)
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class ValidationError(ValueError):
    """Ungültige Benutzereingabe."""


def validate_share_name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise ValidationError("Freigabename muss 1–80 Zeichen lang sein.")
    if not SHARE_NAME_RE.match(name):
        raise ValidationError(
            "Freigabename darf nur Buchstaben, Zahlen, Leerzeichen, _ und - enthalten."
        )
    return name


def validate_share_path(path: str, base_path: str) -> str:
    path = (path or "").strip()
    if not path.startswith("/"):
        raise ValidationError("Pfad muss absolut sein (mit / beginnen).")
    if ".." in path.split("/"):
        raise ValidationError("Pfad darf keine ..-Komponenten enthalten.")

    resolved = Path(path).resolve()
    base = Path(base_path).resolve()

    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValidationError(
            f"Pfad muss innerhalb von {base} liegen (angegeben: {path})."
        ) from exc

    return str(resolved)


def validate_comment(comment: str | None) -> str:
    if comment is None:
        return ""
    comment = comment.strip()
    if len(comment) > 256:
        raise ValidationError("Beschreibung darf maximal 256 Zeichen lang sein.")
    if any(c in comment for c in ("\n", "\r", "\0", "[", "]")):
        raise ValidationError("Beschreibung enthält ungültige Zeichen.")
    return comment


def validate_samba_username(username: str) -> str:
    username = (username or "").strip().lower()
    if not SAMBA_USER_RE.match(username):
        raise ValidationError(
            "Samba-Benutzername: 1–32 Zeichen, Buchstabe am Anfang, "
            "danach Buchstaben, Zahlen, _ oder -."
        )
    return username


def validate_password(password: str, field_name: str = "Passwort") -> str:
    if not password or len(password) < PASSWORD_MIN_LENGTH:
        raise ValidationError(f"{field_name} muss mindestens {PASSWORD_MIN_LENGTH} Zeichen haben.")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValidationError(f"{field_name} darf maximal {PASSWORD_MAX_LENGTH} Zeichen haben.")
    return password


def validate_bind_host(host: str) -> str:
    host = (host or "").strip()
    allowed = {"127.0.0.1", "0.0.0.0", "::1", "::"}
    if host in allowed:
        return host
    # Einfache IPv4-Prüfung
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return host
    raise ValidationError(f"Ungültige Bind-Adresse: {host}")


def parse_valid_users(raw: str) -> list[str]:
    if not raw or not raw.strip():
        return []
    users = []
    for part in raw.replace(",", " ").split():
        users.append(validate_samba_username(part))
    return users


def parse_valid_users_checked(selected: list[str]) -> list[str]:
    """Validiert ausgewählte Benutzernamen aus Checkboxen (ohne Duplikate)."""
    users: list[str] = []
    seen: set[str] = set()
    for name in selected:
        name = (name or "").strip().lower()
        if not name or name in seen:
            continue
        users.append(validate_samba_username(name))
        seen.add(name)
    return users
