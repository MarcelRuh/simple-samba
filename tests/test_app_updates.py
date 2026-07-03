from app.app_updates import is_newer_version, parse_version


def test_parse_version():
    assert parse_version("1.6.0") == (1, 6, 0)
    assert parse_version("v2.10.3") == (2, 10, 3)


def test_is_newer_version():
    assert is_newer_version("1.6.0", "1.5.0")
    assert not is_newer_version("1.5.0", "1.6.0")
    assert not is_newer_version("1.5.0", "1.5.0")
