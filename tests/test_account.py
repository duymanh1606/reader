"""Tách chuỗi dán vào thành email + mật khẩu."""

from __future__ import annotations

import pytest

from reader.account import BadAccount, parse


@pytest.mark.parametrize("raw", [
    "ten@outlook.com|MatKhau123",
    "ten@outlook.com:MatKhau123",
    "ten@outlook.com MatKhau123",
    "  TEN@Outlook.com\tMatKhau123  ",
    "ten@outlook.com|MatKhau123|refresh-token|client-id",
])
def test_doc_duoc_moi_kieu_dan(raw):
    account = parse(raw)
    assert account.email == "ten@outlook.com"
    assert account.password == "MatKhau123"


def test_khong_mat_khau_van_doc_duoc_email():
    assert parse("ten@outlook.com") == parse("ten@outlook.com")
    assert parse("ten@outlook.com").password == ""


def test_mat_khau_co_dau_hai_cham_khong_bi_cat():
    """Email không chứa `:` nhưng mật khẩu thì có - cắt ở `:` đầu tiên là mất
    một nửa mật khẩu."""
    assert parse("ten@outlook.com|a:b:c").password == "a:b:c"


def test_mat_khau_khong_lot_vao_log():
    assert "MatKhau123" not in repr(parse("ten@outlook.com|MatKhau123"))


@pytest.mark.parametrize("raw", ["", "   ", "khong-co-email-nao"])
def test_khong_thay_email_thi_bao_ngay(raw):
    with pytest.raises(BadAccount):
        parse(raw)
