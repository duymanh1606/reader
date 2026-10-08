"""Tách chuỗi dán trên giao diện thành email + mật khẩu.

Người ta dán đủ kiểu: `mail|pass`, `mail:pass`, `mail pass`, có khi kèm thêm
mấy cột nữa (refresh token, client id) mà ở đây không dùng. Chỗ này nhận hết,
lấy đúng hai cột đầu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SEPARATORS = re.compile(r"[|\t;,]| {2,}| +")
EMAIL = re.compile(r"[^\s|:;,]+@[^\s|:;,]+\.[^\s|:;,]+")


class BadAccount(ValueError):
    """Chuỗi dán vào không đọc được thành email (+ mật khẩu)."""


@dataclass
class Account:
    email: str
    password: str = field(default="", repr=False)   # repr=False: không lọt vào log

    def __repr__(self) -> str:                      # pragma: no cover - chỉ để log
        return f"Account(email={self.email!r}, password='***')"


def parse(raw: str) -> Account:
    """Đọc một dòng dán vào. Ném `BadAccount` nếu không thấy email.

    Dấu `:` chỉ được coi là dấu phân cách khi KHÔNG có dấu nào khác: email
    không chứa `:`, nhưng mật khẩu thì có thể - cắt bừa ở dấu `:` đầu tiên là
    cắt mất một nửa mật khẩu dạng `a:b`.
    """
    line = (raw or "").strip()
    if not line:
        raise BadAccount("chưa dán gì cả")
    # Nhiều dòng: lấy dòng đầu có chữ.
    line = next((l.strip() for l in line.splitlines() if l.strip()), "")

    match = EMAIL.search(line)
    if not match:
        raise BadAccount("không thấy địa chỉ email nào trong chuỗi vừa dán")
    email = match.group(0).strip().lower()

    rest = line[match.end():].lstrip()
    if rest[:1] in (":", "|", ";", ",", "\t"):
        rest = rest[1:]
    # Chỉ cột thứ hai là mật khẩu; các cột sau (token, client id) bỏ.
    password = SEPARATORS.split(rest.strip(), maxsplit=1)[0].strip() if rest else ""
    return Account(email=email, password=password)
