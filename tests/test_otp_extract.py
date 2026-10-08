"""Chấm điểm dãy số theo ngữ cảnh: `\\d{6}` là không đủ."""

from __future__ import annotations

from reader.otp_extract import extract_code


def test_lay_ma_co_tu_khoa_dung_truoc():
    found = extract_code("Your verification code is 483921. Do not share it.")
    assert found is not None and found.code == "483921"


def test_lay_ma_co_tu_khoa_dung_sau():
    found = extract_code("392014 is your verification code")
    assert found is not None and found.code == "392014"


def test_khong_tra_so_don_hang():
    assert extract_code("Your order number is 48392105") is None
    assert extract_code("Invoice 483921 has been paid") is None


def test_day_so_khong_co_ngu_canh_thi_bo():
    """0.55 < ngưỡng 0.6: thà không trả mã còn hơn trả nhầm."""
    assert extract_code("Chào bạn, 483921") is None


def test_tu_khoa_phu_dinh_chi_loai_trong_cung_cau():
    found = extract_code("Order shipped. Your code is 483921.")
    assert found is not None and found.code == "483921"


def test_so_trong_link_khong_tinh():
    assert extract_code("Mở https://example.com/t/483921 để xem") is None


def test_hai_ma_manh_ngang_nhau_thi_khong_doan_bua():
    """Hai ứng viên 'ngữ cảnh yếu' sát điểm: trừ 0.3 là xuống dưới ngưỡng."""
    assert extract_code("code 111111 code 222222") is None
