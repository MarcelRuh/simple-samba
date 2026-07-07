"""Sicherheits-Hinweise für Freigaben."""

from __future__ import annotations

from app.samba import Share


def share_security_warnings(shares: list[Share]) -> list[dict[str, str]]:
    """Erzeugt Warnungen für riskante Freigabe-Konfigurationen."""
    warnings: list[dict[str, str]] = []
    for share in shares:
        if not share.enabled:
            continue
        name = share.name
        if share.guest_ok:
            warnings.append({
                "level": "warn",
                "message": f'Freigabe „{name}" erlaubt Gast-Zugriff ohne Anmeldung.',
                "share_name": name,
            })
            continue
        if not share.valid_users:
            warnings.append({
                "level": "warn",
                "message": f'Freigabe „{name}" hat keine erlaubten Benutzer konfiguriert.',
                "share_name": name,
            })
    return warnings
