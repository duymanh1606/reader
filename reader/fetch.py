"""Một lượt lấy mã: mở trình duyệt, đăng nhập Outlook, đọc mã gần nhất.

Chạy trong MỘT luồng từ đầu đến cuối. Playwright bản sync gắn mỗi `page` với
greenlet của luồng tạo ra nó, luồng khác chạm vào là ném `cannot switch to a
different thread` - nên trình duyệt được dựng, dùng và đóng hết bên trong
`run()`, và thứ duy nhất đi ra ngoài là chuỗi trạng thái cùng mã tìm được.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from playwright.sync_api import sync_playwright

from reader import outlook, profile as profile_mo, proxy as proxy_mo
from reader.browser import launch_persistent
from reader.config import Settings
from reader.mail_login import (
    MAX_NOTICE_CLICKS,
    MailLoginBlocked,
    login,
    notice_button,
    sign_out,
)
from reader.outlook import Hit

logger = logging.getLogger(__name__)


@dataclass
class Result:
    hit: Hit | None = None
    error: str | None = None


class Cancelled(RuntimeError):
    """Người dùng bấm Dừng."""


def _closed(exc: Exception) -> bool:
    """Lỗi này là do cửa sổ bị đóng, chứ không phải lỗi thật?"""
    text = str(exc).lower()
    return "closed" in text or "target page" in text or "browser has been closed" in text


def snapshot(page, snap) -> None:
    """Chụp màn hình trang cho giao diện xem, nếu có ai hỏi.

    Trên server không có cửa sổ nào để nhìn, nên không có ảnh thì người dùng
    chỉ thấy mỗi dòng trạng thái và không biết agent đang đứng ở màn hình gì -
    mà "cần bạn đăng nhập" có thể là 2FA, CAPTCHA, hay sai mật khẩu.

    JPEG chất lượng 60: đủ đọc chữ trên màn hình, và nhẹ hơn PNG vài lần cho
    một thứ bị thay mới mỗi nhịp poll. Chụp hỏng thì thôi, không làm đổ lượt.
    """
    if snap is None:
        return
    try:
        snap(page.screenshot(type="jpeg", quality=60, timeout=5000), page.url or "")
    except Exception as exc:
        if _closed(exc):
            raise
        logger.debug("chụp màn hình không xong: %s", exc)


def run(
    email: str,
    password: str,
    settings: Settings,
    report,
    should_stop=None,
    sign_out_after: bool = False,
    snap=None,
) -> Result:
    """Lấy mã OTP gần nhất trong hộp thư `email`.

    `report(status, detail="")` được gọi mỗi khi có gì đáng nói - giao diện đọc
    đúng chuỗi đó. `snap(anh_jpeg, url)` nhận ảnh màn hình mỗi nhịp.
    `should_stop()` trả True thì dừng sớm.
    """
    stop = should_stop or (lambda: False)
    # Nhớ chặng gần nhất đã báo, để nếu lượt ngã vì một lỗi không ngờ thì log
    # nói được nó ngã ở đâu (mở trình duyệt? đăng nhập? đang đọc?).
    last_status = {"v": "đang mở trình duyệt"}
    _report = report

    def report(status: str, detail: str = "") -> None:
        last_status["v"] = status
        _report(status, detail)

    profile_dir = profile_mo.profile_for(settings.profiles_dir, email)
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_mo.clear_stale_lock(profile_dir)

    report("đang mở trình duyệt")
    with sync_playwright() as pw:
        try:
            context = launch_persistent(
                pw,
                user_data_dir=str(profile_dir),
                channel=settings.browser_channel or None,
                headless=settings.headless,
                proxy=proxy_mo.parse(settings.proxy_url),
            )
        except Exception as exc:
            return Result(error=profile_mo.explain_launch_error(exc, profile_dir))

        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(settings.inbox_url, wait_until="domcontentloaded", timeout=60000)
            hit = _watch(page, email, password, settings, report, stop, snap)
            if sign_out_after:
                report("đang đăng xuất")
                sign_out(page)
            return Result(hit=hit)
        except Cancelled:
            return Result(error="bạn đã dừng")
        except MailLoginBlocked as exc:
            return Result(error=str(exc))
        except Exception as exc:
            if _closed(exc):
                return Result(error="cửa sổ trình duyệt đã bị đóng")
            logger.exception("lượt lấy mã của %s đổ ở chặng '%s'",
                             email, last_status["v"])
            return Result(error=f"lỗi: {exc}")
        finally:
            try:
                context.close()
            except Exception:
                pass


def _watch(page, email, password, settings: Settings, report, stop,
           snap=None) -> Hit | None:
    """Vòng đọc hộp thư cho tới khi thấy mã, hoặc hết hạn.

    Thứ tự trong vòng là thứ quyết định đúng/sai, nên viết thẳng ra:
    cửa sổ còn mở → đã đăng nhập chưa → có thật đang ở trong hộp thư không →
    rồi mới quét.
    """
    seen: dict[str, int] = {}
    deadline = time.monotonic() + settings.timeout_seconds
    last_reload = time.monotonic()
    login_failed = False       # đã bế tắc một lần thì không gõ lại mật khẩu
    waiting_for_human = False
    notice_clicks = 0          # màn hình thông báo đã bấm qua, cả sau khi vào
    loops = 0                  # số vòng đã quay, để log chi tiết đánh số được

    logger.debug("hộp thư %s: bắt đầu canh, hạn %ss", email,
                 settings.timeout_seconds)
    while time.monotonic() < deadline:
        loops += 1
        remaining = deadline - time.monotonic()
        logger.debug("hộp thư %s: vòng #%d, còn %.0fs, đã xem %d mail, url=%s",
                     email, loops, remaining, len(seen), (page.url or "")[:60])
        if stop():
            raise Cancelled
        if page.is_closed():
            raise MailLoginBlocked("cửa sổ trình duyệt đã bị đóng")
        snapshot(page, snap)

        if outlook.needs_login(page):
            if login_failed:
                # Để nguyên cửa sổ: 2FA, CAPTCHA hay mật khẩu sai là việc của
                # người. Nếu người làm xong trong lúc này thì vòng sau đi tiếp.
                if not waiting_for_human:
                    report("cần bạn đăng nhập", "agent không tự xử lý được, hãy làm trong cửa sổ vừa mở")
                    waiting_for_human = True
                _sleep(3, stop)
                continue
            if not password:
                # Không có mật khẩu thì không tự đăng nhập, nhưng cũng không bỏ
                # cuộc: phiên nằm lại trong profile nên "một lần" là một lần
                # thật, và lượt sau cùng email này là vào thẳng hộp thư.
                login_failed = True
                waiting_for_human = True
                report("cần bạn đăng nhập",
                       "không có mật khẩu - hãy đăng nhập Outlook trong cửa sổ vừa mở")
                _sleep(3, stop)
                continue
            report("đang đăng nhập Outlook")
            try:
                login(page, email, password,
                      timeout_seconds=settings.login_timeout_seconds,
                      should_stop=stop)
            except MailLoginBlocked as exc:
                if stop():
                    raise Cancelled
                login_failed = True
                logger.warning("hộp thư %s: %s", email, exc)
                report("cần bạn đăng nhập", str(exc))
                snapshot(page, snap)      # đúng màn hình đang chặn, chụp ngay
                continue
            page.goto(settings.inbox_url, wait_until="domcontentloaded", timeout=60000)
            seen.clear()       # hộp thư khác thì những gì đã xem không còn nghĩa
            waiting_for_human = False
            continue

        if not outlook.in_inbox(page):
            # Vào tới nơi rồi mà Outlook còn chen một màn hình thông báo
            # ("Welcome to the new Outlook", mời cài app...) - cùng luật an
            # toàn như lúc đăng nhập: không ô nhập, không dính `BLOCKERS`,
            # nút mang nghĩa "đọc rồi, đi tiếp".
            if notice_clicks < MAX_NOTICE_CLICKS:
                button = notice_button(page)
                if button is not None:
                    notice_clicks += 1
                    report("đang bấm qua màn hình thông báo")
                    try:
                        button.click(timeout=15000)
                        page.wait_for_timeout(2000)
                    except Exception as exc:
                        if _closed(exc):
                            raise
                        logger.debug("bấm qua màn hình thông báo không xong: %s", exc)
                    continue
            report("đang vào hộp thư")
            _sleep(settings.poll_seconds, stop)
            continue

        report("đang đọc hộp thư")
        try:
            hit = outlook.scan_for_code(page, seen)
        except Exception as exc:
            if _closed(exc):
                raise
            logger.warning("quét hộp thư không xong: %s", exc)
            hit = None
        if hit is not None:
            return hit

        _sleep(settings.poll_seconds, stop)
        # Tải lại chỉ là lưới an toàn: Outlook là SPA, mail mới tự hiện trong
        # danh sách nên đọc lại DOM là thấy. Tải lại mỗi nhịp poll chỉ làm trang
        # nháy liên tục mà không nhanh thêm chút nào.
        if time.monotonic() - last_reload >= settings.refresh_seconds:
            last_reload = time.monotonic()
            logger.debug("hộp thư %s: tải lại trang (lưới an toàn)", email)
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                if _closed(exc):
                    raise
                logger.debug("tải lại hộp thư không xong: %s", exc)

    logger.debug("hộp thư %s: hết %ss, dừng canh sau %d vòng, đã xem %d mail",
                 email, settings.timeout_seconds, loops, len(seen))
    return None


def _sleep(seconds: float, stop) -> None:
    """Chờ nhưng vẫn nghe lệnh Dừng - chia nhỏ ra từng nhịp nửa giây."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stop():
            raise Cancelled
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
