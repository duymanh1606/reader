"""Có mã thì gửi một email về hộp thư của bạn.

Tách làm hai phần cố ý: `build` dựng lá thư (thuần, test được không cần mạng)
và `send` mở kết nối SMTP. Phần dễ sai nằm ở nội dung thư, không ở chỗ gọi
`smtplib`.

Mặc định TẮT: không khai máy chủ SMTP và địa chỉ nhận thì không gửi gì cả.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage

logger = logging.getLogger(__name__)

TIMEOUT = 20


@dataclass(frozen=True)
class Mailbox:
    """Chỗ gửi đi và chỗ nhận. `password` không vào log hay repr."""

    host: str = ""
    port: int = 587
    user: str = ""
    password: str = field(default="", repr=False)
    sender: str = ""          # rỗng thì lấy `user`
    to: str = ""
    # 465 là SMTPS (bọc TLS ngay từ đầu), 587 là STARTTLS. Đoán theo cổng chứ
    # không bắt khai thêm một cờ nữa.
    @property
    def ssl(self) -> bool:
        return self.port == 465

    @property
    def ready(self) -> bool:
        """Đủ để gửi chưa? Thiếu một trong ba thì coi như tắt."""
        return bool(self.host and self.to and (self.sender or self.user))

    @property
    def from_addr(self) -> str:
        return self.sender or self.user


def build(box: Mailbox, code: str, email: str, subject: str = "", to: str = "") -> EmailMessage:
    """Lá thư báo mã.

    Mã nằm ngay trên TIÊU ĐỀ: trên điện thoại, thông báo đẩy chỉ hiện tiêu đề,
    nên để mã ở đấy là đọc được mà không phải mở thư.
    """
    thu = EmailMessage()
    thu["Subject"] = f"{code} - mã OTP của {email}"
    thu["From"] = box.from_addr
    thu["To"] = to or box.to
    dong = [f"Mã: {code}", f"Hộp thư: {email}"]
    if subject:
        dong.append(f"Mail: {subject}")
    dong.append("")
    dong.append("Gửi tự động bởi reader.")
    thu.set_content("\n".join(dong))
    return thu


def send(box: Mailbox, code: str, email: str, subject: str = "", to: str = "") -> bool:
    """Gửi thư báo mã. True nếu máy chủ SMTP nhận.

    Không bao giờ ném lỗi: mã đã nằm trong kết quả rồi, gửi hỏng thì chỉ là
    thiếu một cái thông báo chứ không phải mất mã.
    """
    if not box.ready:
        return False
    thu = build(box, code, email, subject, to)
    try:
        mo = smtplib.SMTP_SSL if box.ssl else smtplib.SMTP
        with mo(box.host, box.port, timeout=TIMEOUT) as may:
            if not box.ssl:
                may.starttls()
            if box.user:
                may.login(box.user, box.password)
            may.send_message(thu)
    except Exception as exc:
        logger.warning("không gửi được mail báo mã tới %s: %s", thu["To"], exc)
        return False
    logger.info("đã gửi mã về %s", thu["To"])
    return True
