"""Hilfsfunktionen für Freigabe-Formulare."""

from __future__ import annotations

from app.config import load_config
from app.samba import Share, SambaError, list_samba_users
from app.validators import (
    ValidationError,
    parse_valid_users_checked,
    validate_comment,
    validate_share_name,
    validate_share_path,
)


def default_share_path(base_path: str) -> str:
    return f"{base_path.rstrip('/')}/"


def load_samba_users_for_form() -> list[str]:
    try:
        return list_samba_users()
    except SambaError:
        return []


def share_from_form_values(form) -> Share:
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


def share_from_form(form) -> Share:
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
