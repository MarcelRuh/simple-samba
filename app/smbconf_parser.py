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

SMB_SHARES_INCLUDE = "/etc/samba/smb-shares.conf"
UI_INCLUDE_MARKER = "# Simple Samba UI – verwaltete Freigaben"
_INCLUDE_RE = re.compile(r"^\s*include\s*=\s*(.+)$", re.IGNORECASE)
_SECTION_RE = re.compile(r"^\s*\[(.+?)\]\s*$")

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


@dataclass
class ParsedShareLocated:
    share: ParsedShare
    source_file: str


def _resolve_include_path(include_target: str, base_dir: Path) -> Path:
    target = include_target.strip().strip('"').strip("'")
    path = Path(target)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def collect_smb_conf_files(
    root: Path,
    *,
    seen: set[Path] | None = None,
    skip_paths: set[Path] | None = None,
) -> list[Path]:
    """Sammelt smb.conf und per include eingebundene Dateien (ohne Zyklen)."""
    seen = seen or set()
    skip_paths = skip_paths or set()
    root = root.resolve()
    if root in seen or not root.is_file() or root in skip_paths:
        return []
    seen.add(root)
    files = [root]
    try:
        content = root.read_text(encoding="utf-8")
    except OSError:
        return files
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        match = _INCLUDE_RE.match(line)
        if not match:
            continue
        include_path = _resolve_include_path(match.group(1), root.parent)
        files.extend(
            collect_smb_conf_files(include_path, seen=seen, skip_paths=skip_paths)
        )
    return files


def parse_all_smb_conf_shares(
    root: Path | str = "/etc/samba/smb.conf",
    *,
    skip_paths: set[Path] | None = None,
) -> list[ParsedShare]:
    """Liest Freigaben aus smb.conf inkl. eingebundener Dateien."""
    root_path = Path(root)
    skip = skip_paths or {Path(SMB_SHARES_INCLUDE).resolve()}
    shares: list[ParsedShare] = []
    seen_names: set[str] = set()
    for conf_file in collect_smb_conf_files(root_path, skip_paths=skip):
        try:
            content = conf_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for share in parse_smb_conf_shares(content):
            key = share.name.lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            shares.append(share)
    return shares


def parse_all_smb_conf_shares_with_sources(
    root: Path | str = "/etc/samba/smb.conf",
    *,
    skip_paths: set[Path] | None = None,
) -> list[ParsedShareLocated]:
    root_path = Path(root)
    skip = skip_paths or {Path(SMB_SHARES_INCLUDE).resolve()}
    located: list[ParsedShareLocated] = []
    seen_names: set[str] = set()
    for conf_file in collect_smb_conf_files(root_path, skip_paths=skip):
        try:
            content = conf_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for share in parse_smb_conf_shares(content):
            key = share.name.lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            located.append(ParsedShareLocated(share=share, source_file=str(conf_file.resolve())))
    return located


def ensure_global_smb_include(
    content: str,
    include_path: str = SMB_SHARES_INCLUDE,
) -> str:
    """Stellt sicher, dass smb-shares.conf nur in [global] eingebunden ist."""
    include_line = f"include = {include_path}"
    current_section: str | None = None
    global_has_include = False
    cleaned: list[str] = []

    for line in content.splitlines():
        section_match = _SECTION_RE.match(line)
        if section_match:
            current_section = section_match.group(1).strip().lower()

        include_match = _INCLUDE_RE.match(line)
        if include_match and include_match.group(1).strip().strip('"').strip("'") == include_path:
            if current_section == "global":
                if global_has_include:
                    continue
                global_has_include = True
                cleaned.append(line)
                continue
            continue

        cleaned.append(line)

    if global_has_include:
        result = "\n".join(cleaned)
    else:
        inserted = False
        updated: list[str] = []
        for line in cleaned:
            updated.append(line)
            if not inserted and line.strip().lower() == "[global]":
                updated.append(UI_INCLUDE_MARKER)
                updated.append(f"   {include_line}")
                inserted = True
        if not inserted:
            updated = ["[global]", UI_INCLUDE_MARKER, f"   {include_line}", ""] + cleaned
        result = "\n".join(updated)

    if content.endswith("\n"):
        result += "\n"
    return result


def repair_smb_conf_include(smb_conf_path: Path | str = "/etc/samba/smb.conf") -> bool:
    """Repariert die Include-Zeile in smb.conf. Gibt True zurück bei Änderung."""
    path = Path(smb_conf_path)
    if not path.is_file():
        return False
    original = path.read_text(encoding="utf-8")
    repaired = ensure_global_smb_include(original)
    if repaired == original:
        return False
    path.write_text(repaired, encoding="utf-8")
    return True


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


def comment_out_shares_in_files(
    located: list[ParsedShareLocated],
    section_names: set[str],
) -> dict[Path, str]:
    """Kommentiert Freigaben in den jeweiligen Quelldateien aus."""
    if not section_names:
        return {}
    targets = {name.lower() for name in section_names}
    by_source: dict[str, set[str]] = {}
    for item in located:
        if item.share.name.lower() in targets:
            by_source.setdefault(item.source_file, set()).add(item.share.name)
    updates: dict[Path, str] = {}
    for source_file, names in by_source.items():
        path = Path(source_file)
        updates[path] = comment_out_sections(path.read_text(encoding="utf-8"), names)
    return updates
