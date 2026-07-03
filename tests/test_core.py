import pytest

from app.smbconf_parser import (
    comment_out_sections,
    filter_importable,
    parse_smb_conf_shares,
)
from app.validators import ValidationError, validate_share_name, validate_samba_username


def test_validate_share_name_ok():
    assert validate_share_name("Meine Freigabe") == "Meine Freigabe"


def test_validate_share_name_rejects_empty():
    with pytest.raises(ValidationError):
        validate_share_name("")


def test_validate_samba_username():
    assert validate_samba_username("Max") == "max"


def test_parse_smb_conf_shares():
    content = """
[global]
   workgroup = WORKGROUP

[daten]
   path = /srv/shares/daten
   read only = no
   valid users = alice bob

[homes]
   browseable = no
"""
    shares = parse_smb_conf_shares(content)
    assert len(shares) == 1
    assert shares[0].name == "daten"
    assert shares[0].path == "/srv/shares/daten"
    assert shares[0].valid_users == ["alice", "bob"]


def test_filter_importable():
    shares = parse_smb_conf_shares(
        "[a]\npath=/srv/a\n[b]\npath=/srv/b\n"
    )
    result = filter_importable(shares, {"a"})
    assert [item.name for item in result] == ["b"]


def test_comment_out_sections():
    content = "[global]\nworkgroup = TEST\n\n[share1]\npath = /srv/1\n\n[share2]\npath = /srv/2\n"
    updated = comment_out_sections(content, {"share1"})
    assert "# path = /srv/1" in updated
    assert "[share2]" in updated
    assert "path = /srv/2" in updated
    assert "workgroup = TEST" in updated
