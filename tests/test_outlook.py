"""Đọc trang Outlook: nhận ra trạng thái trang, và quét mã trong danh sách."""

from __future__ import annotations

from reader import outlook
from tests.helpers import inbox_context, signed_out_context


def test_nhan_ra_hop_thu(browser):
    ctx, page = inbox_context(browser)
    try:
        assert not outlook.needs_login(page)
        assert outlook.in_inbox(page)
    finally:
        ctx.close()


def test_trang_gioi_thieu_khong_phai_hop_thu(browser):
    """Chưa đăng nhập, outlook.live.com đá sang trang giới thiệu - trang đó
    không có ô đăng nhập nào, nên `is_login_page` một mình là không đủ."""
    ctx = signed_out_context(browser)
    page = ctx.new_page()
    try:
        page.goto("https://outlook.live.com/mail/0/", wait_until="domcontentloaded")
        assert not outlook.is_login_page(page)
        assert outlook.on_signed_out_page(page)
        assert outlook.needs_login(page)
        assert not outlook.in_inbox(page)
    finally:
        ctx.close()


def test_nhan_ra_trang_dang_nhap(browser):
    ctx = signed_out_context(browser)
    page = ctx.new_page()
    try:
        page.goto("https://login.live.com/login.srf", wait_until="domcontentloaded")
        assert outlook.is_login_page(page)
        assert outlook.needs_login(page)
    finally:
        ctx.close()


def test_quet_lay_ma_trong_noi_dung_mail(browser):
    """Mã không nằm ở dòng xem trước: phải mở mail ra mới thấy."""
    ctx, page = inbox_context(browser)
    try:
        hit = outlook.scan_for_code(page, {})
        assert hit is not None
        assert hit.code == "392014"
        assert hit.where == "nội dung mail"
        assert "TikTok" in hit.preview
    finally:
        ctx.close()


def test_mail_den_muon_thi_luot_quet_sau_thay(browser):
    """Outlook là SPA: mail mới tự hiện trong danh sách, không cần tải lại
    trang - nên đọc lại DOM là đủ."""
    ctx, page = inbox_context(browser, "outlook_inbox_live.html")
    seen: dict[str, int] = {}
    try:
        assert outlook.scan_for_code(page, seen) is None
        page.wait_for_timeout(2500)
        hit = outlook.scan_for_code(page, seen)
        assert hit is not None and hit.code == "771205"
    finally:
        ctx.close()


def test_mail_khong_phai_ma_thi_bo_qua_han(browser):
    """Dòng không có từ khoá nào bị đánh dấu hết lượt ngay, không mở lại."""
    ctx, page = inbox_context(browser)
    seen: dict[str, int] = {}
    try:
        outlook.scan_for_code(page, seen)
        bo_qua = [v for v in seen.values() if v >= outlook.MAX_ATTEMPTS]
        assert len(bo_qua) == len(seen)
    finally:
        ctx.close()


def test_da_lay_roi_thi_khong_lay_lai(browser):
    """`seen` giữ nguyên giữa hai lượt quét: cùng một mail không trả mã hai lần."""
    ctx, page = inbox_context(browser)
    seen: dict[str, int] = {}
    try:
        assert outlook.scan_for_code(page, seen) is not None
        assert outlook.scan_for_code(page, seen) is None
    finally:
        ctx.close()
