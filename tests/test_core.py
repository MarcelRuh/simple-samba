import pytest

from app.smbconf_parser import (
    comment_out_sections,
    ensure_global_smb_include,
    filter_importable,
    infer_shares_base_path,
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


def test_infer_shares_base_path():
    assert infer_shares_base_path([]) == "/srv/shares"
    assert infer_shares_base_path(["/srv/raid5/plex", "/srv/raid5/data"]) == "/srv/raid5"
    assert infer_shares_base_path(["/mnt/nas/files"]) == "/mnt/nas/files"
    assert infer_shares_base_path(["/srv/a", "/mnt/b"]) == "/"


def test_ensure_global_smb_include_repairs_wrong_section():
    content = (
        "[global]\n"
        "   workgroup = WORKGROUP\n\n"
        "[print$]\n"
        "   path = /var/lib/samba/printers\n"
        "   include = /etc/samba/smb-shares.conf\n"
    )
    fixed = ensure_global_smb_include(content)
    assert fixed.count("include = /etc/samba/smb-shares.conf") == 1
    assert "include = /etc/samba/smb-shares.conf" in fixed.split("[print$]")[0]


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
