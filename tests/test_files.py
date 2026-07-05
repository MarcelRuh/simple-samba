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
