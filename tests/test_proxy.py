"""Đọc chuỗi proxy, và giữ mật khẩu proxy ra khỏi log."""

from __future__ import annotations

import pytest

from reader.proxy import describe, parse


def test_rong_thi_la_none_chu_khong_phai_dict_rong():
    """Chromium nhận `--proxy-server=` rỗng là coi như có proxy rỗng, và mọi
    trang đều trắng."""
    assert parse("") is None
    assert parse(None) is None
    assert parse("   ") is None


def test_doc_du_bon_phan():
    assert parse("http://nguoi:matkhau@1.2.3.4:8000") == {
        "server": "http://1.2.3.4:8000", "username": "nguoi", "password": "matkhau",
    }


def test_thieu_scheme_thi_coi_la_http():
    assert parse("1.2.3.4:3128") == {"server": "http://1.2.3.4:3128"}


def test_giu_nguyen_socks5():
    assert parse("socks5://1.2.3.4:1080") == {"server": "socks5://1.2.3.4:1080"}


def test_socks5_kem_mat_khau_thi_bao_ngay():
    """Chromium không gửi user/pass cho SOCKS - để lọt xuống là mọi trang đổ
    ERR_PROXY_CONNECTION_FAILED mà không ai biết vì sao."""
    with pytest.raises(ValueError, match="SOCKS5"):
        parse("socks5://nguoi:matkhau@1.2.3.4:1080")


def test_chuoi_hong_thi_bao_ngay():
    with pytest.raises(ValueError):
        parse("http://:9999")


def test_mo_ta_khong_kem_mat_khau_proxy():
    noi = describe(parse("http://nguoi:matkhau@1.2.3.4:8000"))
    assert "matkhau" not in noi
    assert "nguoi@" in noi and "1.2.3.4:8000" in noi
    assert describe(None) == "không qua proxy"
