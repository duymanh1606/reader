"""Cấu hình. Mọi thứ có mặc định dùng được ngay; đổi bằng biến môi trường.

Trên server, các biến nằm trong `.env` ở gốc dự án (mode 600, đã bị
`.gitignore` chặn - nó mang token và mật khẩu). `load_env_file` nạp file đó
lúc khởi động, nên `python -m reader`, `--check` và unit systemd đọc cùng một
chỗ. Biến đã đặt sẵn trong môi trường thì thắng file.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def load_env_file(path: Path = ENV_FILE) -> bool:
    """Nạp `KEY=value` từ `path` vào `os.environ`. False nếu không có file.

    Biến đã có trong môi trường thì giữ nguyên: `READER_PORT=8080 python -m
    reader` vẫn phải thắng `.env`. Nhận cả `export KEY=...` và giá trị trong
    ngoặc kép/đơn, và chú thích cuối dòng (` # ...`) khi giá trị không nằm
    trong ngoặc; không nội suy `$BIEN` - mật khẩu có `$` phải đi nguyên văn.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.removeprefix("export ").partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            # `KEY=gia-tri   # chú thích`: dấu # chỉ mở chú thích khi đứng sau
            # khoảng trắng, để `pass#123` vẫn là mật khẩu nguyên vẹn.
            value = re.split(r"\s+#", value, maxsplit=1)[0] if value[:1] != "#" else ""
        os.environ.setdefault(key.strip(), value)
    return True


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "có", "co")


def has_display() -> bool:
    """Máy này có màn hình để mở cửa sổ trình duyệt không?

    Trên server thì không, và lúc đó headless là bắt buộc - mở cửa sổ trên một
    máy không ai ngồi trước thì Chromium không khởi động nổi, mà lỗi nó in ra
    chẳng nói gì về nguyên nhân.
    """
    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))


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
    # Cửa sổ trình duyệt hiện ra hay không. Máy có màn hình thì mặc định HIỆN:
    # gặp 2FA hay CAPTCHA thì agent dừng và để nguyên cửa sổ cho bạn làm tiếp.
    # Trên server không màn hình thì buộc phải headless - và lúc đó gặp 2FA là
    # tắc hẳn, không có cửa sổ nào cho người xử lý.
    headless: bool = False
    # Khoá truy cập. Rỗng là ai mở được trang cũng dùng được - chỉ nên thế khi
    # chỉ nghe trên 127.0.0.1.
    token: str = field(default="", repr=False)
    host: str = "127.0.0.1"
    port: int = 5678
    # "chrome" dùng Chrome thật nếu máy có; rỗng thì dùng Chromium của
    # Playwright. Chrome thật bị Microsoft nghi ngờ ít hơn, nhưng server gần
    # như không bao giờ có nó - nên `from_env` chỉ mặc định "chrome" khi máy
    # có màn hình.
    browser_channel: str = "chrome"
    # Proxy cho trình duyệt, dạng http://user:pass@host:port. Xem reader/proxy.py:
    # IP trung tâm dữ liệu là lý do hay gặp nhất khiến Microsoft hỏi 2FA.
    proxy_url: str = field(default="", repr=False)
    # Có mã thì POST về đây. Mỗi lần gọi API truyền `webhook` riêng thì cái đó
    # thắng; không truyền thì dùng cái này.
    # repr=False cho mấy giá trị bí mật: `Settings` bị in ra trong log lỗi và
    # trong output của pytest, và URL webhook thường mang sẵn một cái khoá.
    webhook_url: str = field(default="", repr=False)
    webhook_secret: str = field(default="", repr=False)
    # Gửi mã về hộp thư của bạn. TẮT cho tới khi khai đủ máy chủ SMTP và địa
    # chỉ nhận - xem reader/mailer.py.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = field(default="", repr=False)
    mail_from: str = ""            # rỗng thì lấy `smtp_user`
    mail_to: str = ""
    poll_seconds: int = 5          # nhịp đọc lại DOM hộp thư
    refresh_seconds: int = 120     # nhịp tải lại trang, chỉ là lưới an toàn
    timeout_seconds: int = 180     # hạn cho cả một lượt lấy mã
    login_timeout_seconds: int = 90

    @property
    def mailbox(self):
        """Cấu hình gửi mail, dạng `reader.mailer` dùng. `ready` là công tắc."""
        from reader.mailer import Mailbox

        return Mailbox(
            host=self.smtp_host, port=self.smtp_port, user=self.smtp_user,
            password=self.smtp_password, sender=self.mail_from, to=self.mail_to,
        )

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            profiles_dir=Path(os.getenv("READER_PROFILES", str(cls.profiles_dir))),
            inbox_url=os.getenv("READER_INBOX_URL", cls.inbox_url),
            headless=_flag("READER_HEADLESS", not has_display()),
            token=os.getenv("READER_TOKEN", cls.token).strip(),
            host=os.getenv("READER_HOST", cls.host).strip() or cls.host,
            port=_int("READER_PORT", cls.port),
            proxy_url=os.getenv("READER_PROXY", cls.proxy_url).strip(),
            webhook_url=os.getenv("READER_WEBHOOK", cls.webhook_url).strip(),
            webhook_secret=os.getenv("READER_WEBHOOK_SECRET", cls.webhook_secret).strip(),
            smtp_host=os.getenv("READER_SMTP_HOST", cls.smtp_host).strip(),
            smtp_port=_int("READER_SMTP_PORT", cls.smtp_port),
            smtp_user=os.getenv("READER_SMTP_USER", cls.smtp_user).strip(),
            smtp_password=os.getenv("READER_SMTP_PASSWORD", cls.smtp_password),
            mail_from=os.getenv("READER_MAIL_FROM", cls.mail_from).strip(),
            mail_to=os.getenv("READER_MAIL_TO", cls.mail_to).strip(),
            browser_channel=os.getenv(
                "READER_BROWSER_CHANNEL", cls.browser_channel if has_display() else ""
            ).strip(),
            poll_seconds=_int("READER_POLL_SECONDS", cls.poll_seconds),
            refresh_seconds=_int("READER_REFRESH_SECONDS", cls.refresh_seconds),
            timeout_seconds=_int("READER_TIMEOUT_SECONDS", cls.timeout_seconds),
            login_timeout_seconds=_int(
                "READER_LOGIN_TIMEOUT_SECONDS", cls.login_timeout_seconds
            ),
        )
