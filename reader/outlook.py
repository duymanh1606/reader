"""Đọc trang Outlook web: nhận ra trạng thái trang, và quét mã trong hộp thư.

Không có webhook, không có API hộp thư (bản Microsoft Graph không nằm trong dự
án này). Agent đọc chữ trên trang Outlook như người đọc.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from reader.otp_extract import extract_code

logger = logging.getLogger(__name__)

# Chưa đăng nhập, outlook.live.com/mail/0/ KHÔNG đưa tới màn hình đăng nhập mà
# đá sang trang GIỚI THIỆU trên www.microsoft.com. Trang đó không có ô đăng
# nhập nào, nên "không phải trang đăng nhập" hoàn toàn không có nghĩa là "đã
# vào hộp thư".
SIGNED_OUT_URLS = (
    "microsoft.com/en-us/microsoft-365",
    "microsoft.com/vi-vn/microsoft-365",
    "go.microsoft.com",
)

# Dấu hiệu đang ở màn hình đăng nhập của Microsoft.
LOGIN_MARKERS = [
    "input[name='loginfmt']",
    "input[name='passwd']",
    "#idSIButton9",
    "form[name='f1']",
]

# Dấu hiệu ĐANG Ở TRONG hộp thư. Khác với "không phải trang đăng nhập": một
# trang lỗi, một trang chuyển hướng dở dang, hay trang chính sách riêng tư đều
# không phải trang đăng nhập - mà cũng chẳng phải hộp thư.
MAILBOX_MARKERS = (
    "div[role='listbox']",
    "div[aria-label*='essage list' i]",
    "[data-app-section='MessageList']",
    "div[aria-label*='hộp thư' i]",
    "[aria-label*='Inbox' i]",
)

# Danh sách mail. Outlook đổi markup thường xuyên nên thử nhiều cách.
MESSAGE_ROWS = [
    "div[role='listbox'] div[role='option']",
    "div[aria-label='Message list'] div[role='option']",
    "div[data-convid]",
]
READING_PANE = [
    "div[role='main'] div[aria-label*='essage body' i]",
    "div[role='document']",
    "div#ReadingPaneContainerId",
]

# Lưới THƯA: chỉ để khỏi mở từng mail quảng cáo một. Phần lọc thật nằm ở
# `extract_code`, nơi mỗi dãy số được chấm điểm theo ngữ cảnh.
OTP_HINTS = (
    "verification", "verify", "code", "passcode", "otp", "security",
    "xác minh", "xác thực", "mã", "bảo mật",
)

# Một dòng mail được thử mở tối đa bấy nhiêu lần rồi mới bỏ qua hẳn.
MAX_ATTEMPTS = 3


@dataclass
class Hit:
    """Một mã tìm được, kèm chỗ tìm ra nó - để giao diện nói được vì sao."""

    code: str
    why: str
    where: str
    preview: str


# -- đọc trạng thái trang --------------------------------------------------
def is_login_page(page) -> bool:
    url = page.url or ""
    if "login.live.com" in url or "login.microsoftonline" in url:
        return True
    for selector in LOGIN_MARKERS:
        try:
            if page.locator(selector).first.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


def on_signed_out_page(page) -> bool:
    """Trang giới thiệu dành cho người chưa đăng nhập."""
    url = (page.url or "").lower()
    return any(part in url for part in SIGNED_OUT_URLS)


def needs_login(page) -> bool:
    """Chưa vào được hộp thư: hoặc đang ở form đăng nhập, hoặc bị đá về trang
    giới thiệu.

    Không kiểm bằng danh sách URL hộp thư được phép: `inbox_url` là thứ đặt
    được trong cấu hình.
    """
    return is_login_page(page) or on_signed_out_page(page)


def in_inbox(page) -> bool:
    """Đã THẬT SỰ vào được hộp thư chưa?

    Lớp xác nhận này đứng riêng với `needs_login`: "không phải trang đăng nhập"
    mới chỉ là điều kiện cần. Thiếu nó, agent báo "đang đọc hộp thư" trong khi
    thực ra đang đứng ở một trang chẳng có mail nào.
    """
    if needs_login(page):
        return False
    for selector in MAILBOX_MARKERS:
        try:
            if page.locator(selector).first.is_visible(timeout=500):
                return True
        except Exception:
            continue
    # Không thấy dấu hiệu nào nhưng URL đúng là hộp thư: chấp nhận (hộp thư
    # rỗng, hoặc Outlook lại đổi markup).
    url = (page.url or "").lower()
    return "/mail" in url and "outlook." in url


# -- đọc danh sách mail ----------------------------------------------------
def message_rows(page) -> list:
    for selector in MESSAGE_ROWS:
        try:
            locator = page.locator(selector)
            count = locator.count()
            if count:
                return [locator.nth(i) for i in range(count)]
        except Exception:
            continue
    return []


def reading_pane_text(page) -> str:
    for selector in READING_PANE:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=1000):
                return locator.inner_text(timeout=2000) or ""
        except Exception:
            continue
    try:
        return page.inner_text("body", timeout=2000) or ""
    except Exception:
        return ""


def looks_like_otp_mail(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in OTP_HINTS)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return ""


def scan_for_code(page, seen: dict, max_rows: int = 8) -> Hit | None:
    """Duyệt vài mail MỚI NHẤT, trả về mã đầu tiên tìm được.

    Dòng trên cùng là mail mới nhất, nên "mã đầu tiên tìm được" cũng là mã gần
    nhất - đúng thứ giao diện hỏi.

    `seen` là `{dòng xem trước: số lần đã thử}` - đếm thay vì đánh dấu một lần,
    vì "mở hỏng" có nhiều kiểu không phân biệt được từ ngoài: dòng bị thay giữa
    chừng, click ném lỗi, hay bấm được nhưng khung đọc chưa kịp hiện. Đánh dấu
    ngay lần đầu là bỏ lỡ đúng cái mail đang chờ, vĩnh viễn; thử mãi thì tốn.
    Đếm tới `MAX_ATTEMPTS` rồi thôi.
    """
    rows = message_rows(page)
    scanned = min(len(rows), max_rows)
    logger.debug("quét %d/%d dòng trên cùng", scanned, len(rows))
    candidates = 0
    for index in range(scanned):
        row = rows[index]
        try:
            preview = (row.inner_text(timeout=1000) or "").strip()
        except Exception:
            continue
        if not preview or seen.get(preview, 0) >= MAX_ATTEMPTS:
            continue
        if not looks_like_otp_mail(preview):
            seen[preview] = MAX_ATTEMPTS      # không phải mail mã: bỏ qua hẳn
            continue
        candidates += 1
        seen[preview] = seen.get(preview, 0) + 1

        # Mã thường đã nằm trong dòng xem trước; thử trước khi mở mail, vì mở
        # mail là đánh dấu đã đọc - một việc có ghi, không chỉ đọc.
        found = extract_code(preview)
        if found:
            seen[preview] = MAX_ATTEMPTS
            logger.info("tìm thấy mã trong danh sách (%s)", found.why)
            return Hit(found.code, found.why, "dòng xem trước", _first_line(preview))

        try:
            row.click(timeout=3000)
        except Exception:
            continue
        found = extract_code(reading_pane_text(page))
        if found:
            seen[preview] = MAX_ATTEMPTS
            logger.info("tìm thấy mã trong nội dung mail (%s)", found.why)
            return Hit(found.code, found.why, "nội dung mail", _first_line(preview))
    logger.debug("quét xong: %d mail nghi là mail mã, chưa rút được mã",
                 candidates)
    return None
