"""Cấu hình. Mọi thứ có mặc định dùng được ngay; đổi bằng biến môi trường.

Biến môi trường, không file cấu hình: chỉ có bảy giá trị, và cái duy nhất hay
phải đổi (`READER_HEADLESS`) thường chỉ đổi cho một lần chạy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "có", "co")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Nơi giữ phiên Outlook: mỗi email một thư mục con. Phiên nằm lại ở đây nên
    # lần sau cùng email là không phải đăng nhập lại.
    profiles_dir: Path = ROOT / ".profiles"
    inbox_url: str = "https://outlook.live.com/mail/0/"
    # Cửa sổ trình duyệt hiện ra hay không. Mặc định HIỆN: gặp 2FA hay CAPTCHA
    # thì agent dừng và để nguyên cửa sổ cho bạn làm tiếp - headless thì bạn
    # chẳng còn chỗ nào để làm.
    headless: bool = False
    # "chrome" dùng Chrome thật nếu máy có; rỗng thì dùng Chromium của
    # Playwright. Chrome thật bị Microsoft nghi ngờ ít hơn.
    browser_channel: str = "chrome"
    poll_seconds: int = 5          # nhịp đọc lại DOM hộp thư
    refresh_seconds: int = 120     # nhịp tải lại trang, chỉ là lưới an toàn
    timeout_seconds: int = 180     # hạn cho cả một lượt lấy mã
    login_timeout_seconds: int = 90

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            profiles_dir=Path(os.getenv("READER_PROFILES", str(cls.profiles_dir))),
            inbox_url=os.getenv("READER_INBOX_URL", cls.inbox_url),
            headless=_flag("READER_HEADLESS", cls.headless),
            browser_channel=os.getenv("READER_BROWSER_CHANNEL", cls.browser_channel),
            poll_seconds=_int("READER_POLL_SECONDS", cls.poll_seconds),
            refresh_seconds=_int("READER_REFRESH_SECONDS", cls.refresh_seconds),
            timeout_seconds=_int("READER_TIMEOUT_SECONDS", cls.timeout_seconds),
            login_timeout_seconds=_int(
                "READER_LOGIN_TIMEOUT_SECONDS", cls.login_timeout_seconds
            ),
        )
