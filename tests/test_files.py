import pytest

from app.files import FileBrowserError, resolve_browser_path
from app.samba import Share
from app.validators import ValidationError


def test_resolve_browser_path_share_root():
    share = Share(name="data", path="/srv/raid5/data")
    assert resolve_browser_path(share, "", "/srv/raid5") == "/srv/raid5/data"


def test_resolve_browser_path_subdir():
    share = Share(name="data", path="/srv/raid5/data")
    assert resolve_browser_path(share, "docs/2024", "/srv/raid5") == "/srv/raid5/data/docs/2024"


def test_resolve_browser_path_rejects_traversal():
    share = Share(name="data", path="/srv/raid5/data")
    with pytest.raises(ValidationError):
        resolve_browser_path(share, "../secret", "/srv/raid5")


def test_resolve_browser_path_outside_share():
    share = Share(name="data", path="/srv/raid5/data")
    with pytest.raises(ValidationError):
        resolve_browser_path(share, "../../other", "/srv/raid5")


def test_commit_upload_includes_filename(monkeypatch):
    captured = {}

    def fake_priv_request(command, arg="", body=""):
        captured["command"] = command
        captured["body"] = body
        return True, "ok"

    monkeypatch.setattr("app.files._priv_request", fake_priv_request)
    monkeypatch.setattr(
        "app.files.read_shares",
        lambda _path: [Share(name="data", path="/srv/raid5/data", enabled=True, read_only=False)],
    )
    monkeypatch.setattr(
        "app.files.load_config",
        lambda: {"samba_shares_file": "/tmp/x", "shares_base_path": "/srv/raid5"},
    )

    from app.files import commit_upload

    commit_upload("data", "", "/var/lib/samba-ui/file-staging/upload-abc-test.pdf", "test.pdf")
    assert captured["command"] == "files-commit-upload"
    assert '"filename": "test.pdf"' in captured["body"]
