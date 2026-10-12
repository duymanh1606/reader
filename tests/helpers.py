"""Dựng trang mẫu cho test. Không một request nào ra Internet thật."""

from __future__ import annotations

from pathlib import Path

PAGES = Path(__file__).resolve().parent.parent / "reader" / "testpages"
EMAIL = "nguoidung@outlook.com"
PASSWORD = "MatKhau#2026"


def _html(body: str):
    return lambda route, request: route.fulfill(
        status=200, content_type="text/html; charset=utf-8", body=body
    )


def _js_redirect(route, url: str):
    """Chuyển trang bằng JS, không bằng 302: request sau một 302 tự dựng KHÔNG
    đi qua `route` nữa mà ra Internet thật - test lặng lẽ chạm Microsoft thật."""
    return route.fulfill(status=200, content_type="text/html",
                         body=f"<!doctype html><script>location.href={url!r}</script>")


def inbox_context(browser, name: str = "outlook_inbox.html"):
    """Context trả một trang hộp thư cho mọi URL outlook.live.com."""
    html = (PAGES / name).read_text(encoding="utf-8")
    ctx = browser.new_context()
    ctx.route("**://outlook.live.com/**", _html(html))
    page = ctx.new_page()
    page.goto("https://outlook.live.com/mail/0/", wait_until="domcontentloaded")
    return ctx, page


def signed_out_context(browser, edit=None):
    """outlook.live.com -> trang giới thiệu microsoft.com -> cổng đăng nhập.

    Dựng theo đúng đường thật: chưa đăng nhập thì outlook.live.com/mail/0/ đá
    sang trang giới thiệu, và cổng đăng nhập mới là chỗ có form. `edit` sửa
    trang đăng nhập trước khi trả về.
    """
    form = (PAGES / "outlook_login_flow.html").read_text(encoding="utf-8")
    if edit is not None:
        form = edit(form)
    marketing = (PAGES / "outlook_marketing.html").read_text(encoding="utf-8")
    inbox = (PAGES / "outlook_inbox.html").read_text(encoding="utf-8")
    privacy = "<!doctype html><title>Privacy</title><body><h1>Privacy Statement</h1>"

    # Phiên như cookie của Microsoft: vào được một lần là lần sau mở thẳng hộp
    # thư, không bị đá về trang giới thiệu nữa.
    #
    # Như thật: đăng nhập thẳng ở login.live.com/login.srf chỉ đăng nhập TÀI
    # KHOẢN Microsoft rồi đưa về account.microsoft.com - phiên OUTLOOK chỉ có
    # khi đi qua cổng của chính Outlook (outlook.live.com/owa/?nlp=1).
    session = {"vao_duoc": False, "da_dang_xuat": 0, "qua_outlook": False}
    account = ("<!doctype html><title>Microsoft account | Home</title>"
               "<body><h1>Account</h1><a href='#'>Change password</a>")

    def portal(route, request):
        if "logout" in request.url:
            session["vao_duoc"] = False
            session["da_dang_xuat"] += 1
            return route.fulfill(status=200, content_type="text/html",
                                 body="<!doctype html><title>Signed out</title>")
        return route.fulfill(status=200, content_type="text/html; charset=utf-8",
                             body=form)

    def mailbox(route, request):
        # Nhập mật khẩu xong, form đưa về .../mail/0/?signedin=1: tài khoản đã
        # xác thực, NHƯNG phiên Outlook chưa có - Microsoft đưa về trang tài
        # khoản (đúng lỗi thật người dùng gặp).
        if "signedin=1" in request.url:
            session["qua_outlook"] = True   # tài khoản đã đăng nhập
            if not session["vao_duoc"]:
                return _js_redirect(route, "https://account.microsoft.com/?refd=account.live.com")
        # owa?nlp=1: chỉ lập được phiên Outlook KHI tài khoản đã xác thực. Chưa
        # thì owa đá ngược về trang giới thiệu - đúng vòng lặp đã làm kẹt.
        if "nlp=1" in request.url:
            if session["qua_outlook"]:
                session["vao_duoc"] = True
            else:
                return route.fulfill(status=302, headers={
                    "location": "https://www.microsoft.com/en-us/microsoft-365/outlook/x"})
        if session["vao_duoc"]:
            return route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                 body=inbox)
        return route.fulfill(
            status=302,
            headers={"location": "https://www.microsoft.com/en-us/microsoft-365/outlook/x"},
        )

    ctx = browser.new_context()
    ctx.route("**://outlook.live.com/**", mailbox)
    ctx.route("**://www.microsoft.com/en-us/privacy/**", _html(privacy))
    ctx.route("**://www.microsoft.com/**", _html(marketing))
    ctx.route("**://login.live.com/**", portal)
    ctx.route("**://account.microsoft.com/**", _html(account))
    ctx.session = session
    return ctx
