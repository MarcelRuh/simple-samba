"""Tests für sichere Pfadauflösung in Freigaben."""

from __future__ import annotations

import pytest

from app.path_security import relative_path_parts, safe_resolve_under_root
from app.validators import ValidationError


def test_relative_path_parts_matches_subpath(tmp_path):
    root = tmp_path / "share"
    root.mkdir()
    sub = root / "docs" / "file.txt"
    sub.parent.mkdir()
    sub.touch()
    assert relative_path_parts(root, sub) == "docs/file.txt"


def test_safe_resolve_under_root_subdir(tmp_path):
    root = tmp_path / "share"
    docs = root / "docs"
    docs.mkdir(parents=True)
    assert safe_resolve_under_root(root, "docs") == docs.resolve()


def test_safe_resolve_rejects_traversal(tmp_path):
    root = tmp_path / "share"
    root.mkdir()
    with pytest.raises(ValidationError):
        safe_resolve_under_root(root, "../secret")


def test_safe_resolve_rejects_symlink(tmp_path):
    root = tmp_path / "share"
    root.mkdir()
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "file.txt").write_text("x", encoding="utf-8")
    link = root / "link"
    link.symlink_to(secret)
    with pytest.raises(ValidationError, match="Symbolische Links"):
        safe_resolve_under_root(root, "link/file.txt")


def test_safe_resolve_rejects_symlink_escape(tmp_path):
    root = tmp_path / "share"
    root.mkdir()
    link = root / "escape"
    link.symlink_to(tmp_path)
    with pytest.raises(ValidationError, match="Symbolische Links"):
        safe_resolve_under_root(root, "escape/secret")
