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
    session = {"vao_duoc": False, "da_dang_xuat": 0}

    def portal(route, request):
        if "logout" in request.url:
            session["vao_duoc"] = False
            session["da_dang_xuat"] += 1
            return route.fulfill(status=200, content_type="text/html",
                                 body="<!doctype html><title>Signed out</title>")
        return route.fulfill(status=200, content_type="text/html; charset=utf-8",
                             body=form)

    def mailbox(route, request):
        if "signedin=1" in request.url:
            session["vao_duoc"] = True
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
    ctx.session = session
    return ctx
