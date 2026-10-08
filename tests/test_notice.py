"""Luật bấm qua màn hình thông báo: bấm cái gì, và không bấm cái gì.

Kiểm thẳng `notice_button` trên từng màn hình dựng tay - đi qua cả luồng đăng
nhập cho mỗi trường hợp thì mỗi test mất gần một phút, mà thứ đang kiểm chỉ là
một quyết định.
"""

from __future__ import annotations

import pytest

from reader.mail_login import notice_button

MAN_HINH = "https://login.live.com/man-hinh"


@pytest.fixture
def screen(browser):
    """Mở một màn hình dựng tay, dưới URL của Microsoft."""
    pages = []

    def _open(body: str, url: str = MAN_HINH):
        page = browser.new_page()
        page.route("**://login.live.com/**", lambda route, request: route.fulfill(
            status=200, content_type="text/html; charset=utf-8",
            body=f"<!doctype html><meta charset='utf-8'><body>{body}",
        ))
        page.route("**://ke-la.example/**", lambda route, request: route.fulfill(
            status=200, content_type="text/html; charset=utf-8",
            body=f"<!doctype html><meta charset='utf-8'><body>{body}",
        ))
        page.goto(url, wait_until="domcontentloaded")
        pages.append(page)
        return page

    yield _open
    for page in pages:
        page.close()


def test_man_hinh_chi_de_thong_bao_thi_bam(screen):
    page = screen("<h1>We're updating our terms</h1>"
                  "<p>We have updated the Microsoft Services Agreement.</p>"
                  "<button>Next</button>")
    assert notice_button(page) is not None


def test_man_hinh_chua_tung_gap_bao_gio_cung_bam(screen):
    """Luật là luật chung, không phải danh sách tên màn hình: một thông báo
    hoàn toàn mới vẫn đi qua được."""
    page = screen("<h1>Welcome to the new Outlook</h1>"
                  "<p>Mọi thứ bạn cần, gọn trong một chỗ.</p>"
                  "<button>Got it</button>")
    assert notice_button(page) is not None


def test_co_o_nhap_thi_khong_bam(screen):
    """Có ô nhập nghĩa là màn hình đang HỎI, không phải thông báo."""
    page = screen("<h1>Verify your email</h1>"
                  "<input name='proofconfirmation' type='email'>"
                  "<button>Next</button>")
    assert notice_button(page) is None


def test_co_danh_sach_chon_thi_khong_bam(screen):
    page = screen("<h1>How would you like to sign in?</h1>"
                  "<select><option>Email</option><option>Phone</option></select>"
                  "<button>Next</button>")
    assert notice_button(page) is None


def test_dinh_hai_buoc_thi_khong_bam_du_khong_co_o_nhap(screen):
    """Màn hình trung gian của 2FA: chỉ có chữ và nút Next, nhưng bấm là đi
    vào đúng thứ agent không được tự làm."""
    page = screen("<h1>Help us protect your account</h1>"
                  "<p>We'll text a code to your phone to verify it's you.</p>"
                  "<button>Next</button>")
    assert notice_button(page) is None


def test_dinh_captcha_thi_khong_bam(screen):
    page = screen("<h1>Prove you're human</h1>"
                  "<p>Press and hold the button below.</p>"
                  "<button>Continue</button>")
    assert notice_button(page) is None


def test_khong_bam_nut_mo_trang_khac(screen):
    """"Learn more" là đi khỏi luồng đăng nhập, không phải đi tiếp."""
    page = screen("<h1>We're updating our terms</h1>"
                  "<a href='#'>Learn more about these updates</a>")
    assert notice_button(page) is None


def test_khong_bam_nut_gui_ma_di(screen):
    page = screen("<h1>Thông báo</h1><p>Chỉ là một lời nhắn.</p>"
                  "<button>Send code</button>")
    assert notice_button(page) is None


def test_khong_bam_nut_dang_xuat_hay_xoa(screen):
    page = screen("<h1>Thông báo</h1><p>Chỉ là một lời nhắn.</p>"
                  "<button>Sign out</button><button>Delete account</button>")
    assert notice_button(page) is None


def test_khop_ca_ten_nut_chu_khong_khop_mot_phan(screen):
    """Khớp một phần thì "OK" trúng luôn "Book now"."""
    page = screen("<h1>Thông báo</h1><p>Chỉ là một lời nhắn.</p>"
                  "<button>Book now</button>")
    assert notice_button(page) is None


def test_hoa_thuong_va_khoang_trang_thua_khong_lam_lo(screen):
    page = screen("<h1>Thông báo</h1><p>Chỉ là một lời nhắn.</p>"
                  "<button>  next  </button>")
    assert notice_button(page) is not None


def test_ten_mien_la_thi_khong_bam_gi_ca(screen):
    """Trang lạ thì ngay cả nút "OK" cũng không biết nó làm gì."""
    page = screen("<h1>Thông báo</h1><p>Chỉ là một lời nhắn.</p>"
                  "<button>OK</button>", url="https://ke-la.example/trang")
    assert notice_button(page) is None


def test_nut_nam_trong_iframe_van_tim_ra(screen):
    page = screen("<div id='c'></div><script>"
                  "const f=document.createElement('iframe');"
                  "f.srcdoc=`<h1>A quick note about your Microsoft account</h1>"
                  "<p>Your important things are right here.</p>"
                  "<button>OK</button>`;"
                  "document.getElementById('c').append(f);</script>")
    page.wait_for_timeout(300)
    assert notice_button(page) is not None
