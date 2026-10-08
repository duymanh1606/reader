"""Vòng đọc hộp thư: đăng nhập rồi lấy mã, và những chỗ nó phải dừng."""

from __future__ import annotations

import pytest

from reader.fetch import Cancelled, _watch
from reader.mail_login import MailLoginBlocked
from tests.helpers import EMAIL, PASSWORD, signed_out_context


class Report:
    """Ghi lại từng trạng thái agent báo ra, như giao diện nhận được."""

    def __init__(self):
        self.lines: list[tuple[str, str]] = []

    def __call__(self, status: str, detail: str = "") -> None:
        self.lines.append((status, detail))

    @property
    def statuses(self) -> list[str]:
        return [s for s, _ in self.lines]


def _start(browser, edit=None):
    ctx = signed_out_context(browser, edit)
    page = ctx.new_page()
    page.goto("https://outlook.live.com/mail/0/", wait_until="domcontentloaded")
    return ctx, page


def test_dang_nhap_roi_lay_duoc_ma(browser, settings):
    """Cả đường thật: trang giới thiệu -> cổng đăng nhập -> bẫy không mật khẩu
    -> mật khẩu -> 'Stay signed in?' -> hộp thư -> mã."""
    ctx, page = _start(browser)
    report = Report()
    try:
        hit = _watch(page, EMAIL, PASSWORD, settings, report, lambda: False)
        assert hit is not None and hit.code == "392014"
        assert "đang đăng nhập Outlook" in report.statuses
        assert "đang đọc hộp thư" in report.statuses
    finally:
        ctx.close()


def test_bam_qua_man_hinh_thong_bao_sau_khi_go_mat_khau(browser, settings):
    """Gõ mật khẩu xong, Microsoft chen vào "We're updating our terms" rồi
    "A quick note about your Microsoft account" (nằm trong iframe) mới tới
    "Stay signed in?". Không bấm qua là ngồi hết hạn ở đấy."""
    ctx, page = _start(browser)
    # Trang mẫu báo qua console: đăng nhập xong là nó chuyển sang
    # outlook.live.com, mọi cờ đặt trên `window` mất sạch.
    passed: list[str] = []
    page.on("console", lambda msg: passed.append(msg.text)
            if msg.text.startswith("passed:") else None)
    try:
        hit = _watch(page, EMAIL, PASSWORD, settings, Report(), lambda: False)
        assert "passed:terms" in passed, "chưa bấm qua màn điều khoản"
        assert "passed:note" in passed, "chưa bấm qua màn 'a quick note' trong iframe"
        assert hit is not None and hit.code == "392014"
    finally:
        ctx.close()


def test_khong_cham_vao_bay_gui_ma_sang_email_phu(browser, settings):
    """Ô ghi nhãn 'Email' ở màn hình giữa là chỗ nhập địa chỉ PHỤ. Gõ vào đấy
    là đẩy mã sang một hộp thư khác hẳn."""
    ctx, page = _start(browser)
    try:
        _watch(page, EMAIL, PASSWORD, settings, Report(), lambda: False)
        typed = page.evaluate("() => window.__typed || {}")
        # Cùng cái cờ này cũng bắt luôn "Learn more about these updates" ở màn
        # điều khoản: bấm vào đó là lạc khỏi luồng đăng nhập.
        assert not typed.get("trap")
    finally:
        ctx.close()


def test_mat_khau_chi_go_tren_ten_mien_microsoft(browser, settings):
    """Trang đăng nhập nằm ở tên miền lạ: dừng, không gõ gì."""
    ctx = signed_out_context(browser)
    ctx.route(
        "**://ke-gia-mao.example/**",
        lambda route, request: route.fulfill(
            status=200, content_type="text/html",
            body="<!doctype html><body><form name=f1>"
                 "<input name=loginfmt><input name=passwd></form>",
        ),
    )
    page = ctx.new_page()
    try:
        page.goto("https://ke-gia-mao.example/login", wait_until="domcontentloaded")
        report = Report()
        hit = _watch(page, EMAIL, PASSWORD, settings, report, lambda: False)
        assert hit is None
        # `needs_login` nhận ra form này (nó có `form[name=f1]`), nhưng
        # `_trusted` chặn trước khi gõ - và hai ô vẫn rỗng.
        assert report.statuses[-1] == "cần bạn đăng nhập"
        assert any("tên miền lạ" in detail for _, detail in report.lines)
        assert page.input_value("input[name=passwd]") == ""
        assert page.input_value("input[name=loginfmt]") == ""
    finally:
        ctx.close()


def test_hai_buoc_thi_giao_lai_cho_nguoi(browser, settings):
    """2FA: agent dừng, báo 'cần bạn đăng nhập', và KHÔNG gõ lại mật khẩu."""
    two_fa = (
        "<p>Enter the code we sent to your phone</p>"
        "<input name='otc'>"
    )
    ctx, page = _start(browser, edit=lambda html: html.replace(
        '<div id="step-password" style="display:none">',
        f'<div id="step-2fa">{two_fa}</div><div id="step-password" style="display:none">',
    ))
    report = Report()
    try:
        hit = _watch(page, EMAIL, PASSWORD, settings, report, lambda: False)
        assert hit is None
        assert "cần bạn đăng nhập" in report.statuses
        # Một lần bế tắc là thôi: đếm số lần nó thử đăng nhập lại.
        assert report.statuses.count("đang đăng nhập Outlook") == 1
    finally:
        ctx.close()


def test_khong_co_mat_khau_thi_nho_nguoi_dang_nhap(browser, settings):
    ctx, page = _start(browser)
    report = Report()
    try:
        hit = _watch(page, EMAIL, "", settings, report, lambda: False)
        assert hit is None
        assert report.lines[0][0] == "cần bạn đăng nhập"
        assert "không có mật khẩu" in report.lines[0][1]
        assert "đang đăng nhập Outlook" not in report.statuses
    finally:
        ctx.close()


def test_chup_duoc_man_hinh_that(browser, settings):
    """Ảnh phải là JPEG thật, chụp từ đúng trang đang đứng."""
    ctx, page = _start(browser)
    anh = []
    try:
        _watch(page, EMAIL, "", settings, Report(), lambda: False,
               snap=lambda data, url: anh.append((data, url)))
        assert anh, "không chụp được kiểu nào"
        data, url = anh[0]
        assert data[:3] == b"\xff\xd8\xff"        # dấu đầu file JPEG
        assert len(data) > 1000
        assert url.startswith("http")
    finally:
        ctx.close()


def test_bam_dung_thi_dung_ngay(browser, settings):
    ctx, page = _start(browser)
    try:
        with pytest.raises(Cancelled):
            _watch(page, EMAIL, PASSWORD, settings, Report(), lambda: True)
    finally:
        ctx.close()


def test_cua_so_bi_dong_thi_khong_ngoi_het_gio(browser, settings):
    ctx, page = _start(browser)
    try:
        page.close()
        with pytest.raises(MailLoginBlocked):
            _watch(page, EMAIL, PASSWORD, settings, Report(), lambda: False)
    finally:
        ctx.close()
