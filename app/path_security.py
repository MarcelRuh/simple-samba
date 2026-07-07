"""Sichere Pfadauflösung in Freigaben ohne Symlink-Escape."""

from __future__ import annotations

from pathlib import Path

from app.validators import ValidationError


def relative_path_parts(root: Path, candidate: Path) -> str | None:
    """Relative Pfadteile von root zu candidate (ohne resolve auf candidate)."""
    root_parts = root.resolve().parts
    cand_parts = candidate.parts
    if len(cand_parts) < len(root_parts):
        return None
    if cand_parts[: len(root_parts)] != root_parts:
        return None
    rel_parts = cand_parts[len(root_parts) :]
    return "/".join(rel_parts)


def safe_resolve_under_root(root: Path, relative: str = "") -> Path:
    """Löst einen Pfad unter root auf und blockiert symbolische Links."""
    if root.is_symlink():
        raise ValidationError("Freigabe-Wurzel darf kein symbolischer Link sein.")

    root_resolved = root.resolve()
    current = root_resolved
    rel = (relative or "").strip().replace("\\", "/").strip("/")

    if rel:
        for part in rel.split("/"):
            if not part or part == ".":
                continue
            if part == "..":
                raise ValidationError("Ungültiger Pfad.")
            current = current / part
            if current.is_symlink():
                raise ValidationError("Symbolische Links sind in Freigaben nicht erlaubt.")

    try:
        resolved = current.resolve(strict=False)
        resolved.relative_to(root_resolved)
    except (ValueError, OSError) as exc:
        raise ValidationError("Pfad liegt außerhalb der Freigabe.") from exc
    return resolved
