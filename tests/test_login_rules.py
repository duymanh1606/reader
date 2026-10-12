"""Gõ cái gì vào ô nào - phần dễ sai nhất của luồng đăng nhập Microsoft.

Kiểm thẳng `_Login` trên trang dựng tay: đi cả luồng cho mỗi trường hợp thì
mỗi test mất gần một phút, mà thứ đang kiểm chỉ là một quyết định.
"""

from __future__ import annotations

import pytest

from reader.mail_login import _Login, _stay_signed_in

EMAIL = "nguoidung@outlook.com"
PASSWORD = "MatKhau#2026"


@pytest.fixture
def screen(browser):
    pages = []

    def _open(body: str):
        page = browser.new_page()
        page.route("**://login.live.com/**", lambda route, request: route.fulfill(
            status=200, content_type="text/html; charset=utf-8",
            body=f"<!doctype html><meta charset='utf-8'><body>{body}",
        ))
        page.goto("https://login.live.com/login.srf", wait_until="domcontentloaded")
        pages.append(page)
        return page

    yield _open
    for page in pages:
        page.close()


def test_go_dia_chi_vao_o_dang_nhap(screen):
    # `onclick=return false`: để form đừng gửi đi và tải lại trang - tải lại
    # là ô rỗng trở lại, và test hoá ra đang đo sai thứ.
    page = screen("<form name='f1' onsubmit='return false'>"
                  "<input name='loginfmt' type='email'>"
                  "<input id='idSIButton9' type='submit' onclick='return false'>"
                  "</form>")
    _Login(page, EMAIL, PASSWORD).type_and_submit()
    assert page.input_value("input[name='loginfmt']") == EMAIL


def test_stay_signed_in_bam_yes_khong_bam_nut_dong(screen):
    # Form Fluent mới có nút X đóng cũng là button[type='submit'] và đứng trước
    # nút "Yes". Phải bấm "Yes", không được bấm nút X (sẽ treo/bỏ việc).
    page = screen(
        "<p>Stay signed in?</p>"
        "<button type='submit' id='close-button' aria-label='Close' "
        "data-testid='dismissIcon' onclick=\"document.title='DONG'\">X</button>"
        "<button type='submit' onclick=\"document.title='YES'\">Yes</button>"
        "<button type='submit' onclick=\"document.title='NO'\">No</button>"
    )
    assert _stay_signed_in(page) is True
    assert page.title() == "YES"


def test_go_mat_khau_vao_o_mat_khau(screen):
    page = screen("<form name='f1' onsubmit='return false'>"
                  "<input name='passwd' type='password'>"
                  "<input id='idSIButton9' type='submit' onclick='return false'>"
                  "</form>")
    _Login(page, EMAIL, PASSWORD).type_and_submit()
    assert page.input_value("input[name='passwd']") == PASSWORD


def test_go_mat_khau_xong_thi_khong_go_dia_chi_vao_o_xac_minh(screen):
    """Màn hình sau mật khẩu: "nhập địa chỉ đầy đủ để xác minh". Ô đó KHÔNG
    phải chỗ nhập lại địa chỉ đăng nhập - gõ vào là đẩy mã sang hộp thư khác,
    và biến một màn hình còn đọc được thành 2FA thật.

    Đây đúng là thứ đã xảy ra trên server: sau "đã nhập mật khẩu" lại có thêm
    một dòng "đã nhập địa chỉ", rồi mới tới "đang hỏi xác thực hai bước".
    """
    page = screen(
        "<div id='pw'><form name='f1'><input name='passwd' type='password'>"
        "<input id='idSIButton9' type='submit'></form></div>"
        "<div id='verify' style='display:none'>"
        "<p>Enter your full email address to verify</p>"
        "<input name='proofconfirmation' type='email'>"
        "<button id='send'>Send code</button></div>"
        "<script>idSIButton9.onclick = () => {"
        "  pw.style.display='none'; verify.style.display='block'; return false; };"
        "</script>"
    )
    session = _Login(page, EMAIL, PASSWORD)
    session.type_and_submit()                      # gõ mật khẩu, bấm Next
    page.wait_for_timeout(300)
    session.type_and_submit()                      # màn hình xác minh hiện ra
    assert page.input_value("input[name='proofconfirmation']") == ""


def test_da_go_dia_chi_roi_thi_khong_go_vao_mot_o_email_bat_ky(screen):
    """Ô `loginfmt` là ô đăng nhập của Microsoft; một ô `type=email` khác hiện
    ra sau đó là ô xác minh."""
    page = screen(
        "<div id='one'><form name='f1'><input name='loginfmt' type='email'>"
        "<input id='idSIButton9' type='submit'></form></div>"
        "<div id='two' style='display:none'>"
        "<input name='proofconfirmation' type='email'></div>"
        "<script>idSIButton9.onclick = () => {"
        "  one.style.display='none'; two.style.display='block'; return false; };"
        "</script>"
    )
    session = _Login(page, EMAIL, PASSWORD)
    session.type_and_submit()
    page.wait_for_timeout(300)
    session.type_and_submit()
    assert page.input_value("input[name='proofconfirmation']") == ""


def test_khong_go_gi_tren_ten_mien_la(browser):
    page = browser.new_page()
    page.route("**://ke-gia-mao.example/**", lambda route, request: route.fulfill(
        status=200, content_type="text/html",
        body="<!doctype html><body><form name=f1><input name=loginfmt>"
             "<input name=passwd type=password></form>",
    ))
    try:
        page.goto("https://ke-gia-mao.example/login", wait_until="domcontentloaded")
        from reader.mail_login import MailLoginBlocked

        with pytest.raises(MailLoginBlocked):
            _Login(page, EMAIL, PASSWORD).type_and_submit()
        assert page.input_value("input[name='passwd']") == ""
    finally:
        page.close()


def test_cong_dang_nhap_khong_mo_duoc_thi_noi_loi_proxy(browser):
    """Proxy chặn login.live.com: mọi điều hướng hỏng, trang là chrome-error.
    `login()` phải nổi lỗi rõ (gợi ý đổi IP) sau vài nhịp, thay vì báo nhầm
    "đã vào được" rồi để `fetch` lặp vô tận."""
    from reader.mail_login import login, MailLoginBlocked

    page = browser.new_page()
    page.route("**/*", lambda route, request: route.abort())
    try:
        with pytest.raises(MailLoginBlocked, match="proxy"):
            login(page, EMAIL, PASSWORD, timeout_seconds=15)
    finally:
        page.close()


def test_mat_khau_bi_tu_choi_thi_khong_go_mai(screen):
    """Microsoft từ chối mà vẫn hiện ô mật khẩu: trước đây agent gõ lại cứ
    hai nhịp một lần tới hết 90s - đúng cách làm tài khoản bị khoá. Giờ gõ
    tối đa MAX_PASSWORD_TRIES lần rồi dừng, kèm lý do."""
    from reader.mail_login import MAX_PASSWORD_TRIES, MailLoginBlocked

    page = screen("<form name='f1' onsubmit='return false'>"
                  "<input name='passwd' type='password'>"
                  "<input id='idSIButton9' type='submit' onclick='return false'>"
                  "</form>")
    session = _Login(page, EMAIL, PASSWORD)
    with pytest.raises(MailLoginBlocked, match="mật khẩu"):
        for _ in range(4 * MAX_PASSWORD_TRIES):
            session.type_and_submit()
    assert session.password_tries == MAX_PASSWORD_TRIES


def test_nhan_ra_sai_mat_khau_tren_trang_tieng_viet():
    from reader.mail_login import blocker_in

    assert blocker_in(
        "tài khoản hoặc mật khẩu của bạn không chính xác. nếu bạn không nhớ "
        "mật khẩu của mình, hãy đặt lại ngay bây giờ."
    ) == "sai mật khẩu"
