"""smb.conf parsen und Freigaben für den Import-Assistenten aufbereiten."""

from __future__ import annotations

import configparser
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

SKIP_SECTIONS = frozenset({
    "global",
    "homes",
    "printers",
    "print$",
})

_BOOL_YES = frozenset({"yes", "true", "1", "on"})


@dataclass
class ParsedShare:
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

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_bool(value: str, default: bool) -> bool:
    if not value:
        return default
    return value.strip().lower() in _BOOL_YES


def parse_smb_conf_shares(content: str) -> list[ParsedShare]:
    """Liest Freigabe-Abschnitte aus smb.conf-Text (ohne include-Auflösung)."""
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

    shares: list[ParsedShare] = []
    for section in parser.sections():
        key = section.strip().lower()
        if key in SKIP_SECTIONS:
            continue
        opts = parser[section]
        path = opts.get("path", "").strip()
        if not path:
            continue
        valid_users_raw = opts.get("valid users", "").strip()
        users = [u for u in re.split(r"[\s,]+", valid_users_raw) if u]
        available = opts.get("available", "yes").strip().lower()
        shares.append(
            ParsedShare(
                name=section.strip(),
                path=path,
                comment=opts.get("comment", "").strip(),
                browseable=_parse_bool(opts.get("browseable", "yes"), True),
                read_only=_parse_bool(opts.get("read only", "no"), False),
                guest_ok=_parse_bool(opts.get("guest ok", "no"), False),
                valid_users=users,
                enabled=available != "no",
                create_mask=opts.get("create mask", "0660").strip() or "0660",
                directory_mask=opts.get("directory mask", "0770").strip() or "0770",
            )
        )
    return shares


def infer_shares_base_path(paths: list[str], default: str = "/srv/shares") -> str:
    """Ermittelt ein gemeinsames Basisverzeichnis für vorhandene Freigabe-Pfade."""
    resolved: list[str] = []
    for raw in paths:
        path = (raw or "").strip()
        if not path.startswith("/"):
            continue
        if ".." in path.split("/"):
            continue
        resolved.append(str(Path(path).resolve()))
    if not resolved:
        return default
    common = os.path.commonpath(resolved)
    if common == "/":
        return "/"
    return common


def filter_importable(
    smbconf_shares: list[ParsedShare],
    existing_names: set[str],
) -> list[ParsedShare]:
    """Freigaben aus smb.conf, die noch nicht in smb-shares.conf stehen."""
    existing = {name.lower() for name in existing_names}
    result: list[ParsedShare] = []
    seen: set[str] = set()
    for share in smbconf_shares:
        key = share.name.lower()
        if key in existing or key in seen:
            continue
        seen.add(key)
        result.append(share)
    return result


def comment_out_sections(content: str, section_names: set[str]) -> str:
    """Kommentiert gewählte [abschnitt]-Blöcke in smb.conf aus."""
    if not section_names:
        return content

    targets = {name.lower() for name in section_names}
    lines = content.splitlines()
    output: list[str] = []
    in_target = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            in_target = section in targets
            if in_target:
                output.append(f"# Simple Samba UI – importiert nach smb-shares.conf")
        if in_target:
            if not line.lstrip().startswith("#"):
                output.append(f"# {line}")
            else:
                output.append(line)
        else:
            output.append(line)

    result = "\n".join(output)
    if content.endswith("\n"):
        result += "\n"
    return result
