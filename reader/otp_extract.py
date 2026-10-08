"""Lấy mã OTP từ nội dung một email.

`\\d{6}` là không đủ: mail đầy số đơn hàng, số điện thoại, năm, giá tiền. Ở đây
mỗi dãy số được chấm điểm theo ngữ cảnh quanh nó, và những dãy trông giống mã
nhưng không phải thì bị loại thẳng.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Từ khoá nghĩa là "số cạnh tôi chính là mã" (Anh + Việt).
STRONG_BEFORE = [
    "verification code", "verify code", "security code", "one-time password",
    "one time password", "otp code", "passcode", "confirmation code",
    "access code", "login code", "sign-in code", "authentication code",
    "mã xác minh", "mã xác thực", "mã otp", "mã bảo mật", "mã đăng nhập",
]
STRONG_AFTER = [
    "is your verification code", "is your security code", "is your code",
    "is your otp", "is your login code", "là mã xác minh", "là mã xác thực",
]
WEAK = ["code", "mã", "pin"]

# Ngữ cảnh nghĩa là "số này KHÔNG phải mã".
NEGATIVE = [
    "order", "invoice", "receipt", "reference", "tracking", "shipment",
    "transaction", "account number", "card ending", "phone", "telephone",
    "mobile", "hotline", "zip", "amount", "total", "price", "usd", "vnd",
    "đơn hàng", "hoá đơn", "hóa đơn", "số điện thoại", "tổng tiền",
    "copyright", "unsubscribe", "version",
]

_STRONG_BEFORE_RE = re.compile("|".join(map(re.escape, STRONG_BEFORE)), re.IGNORECASE)
_STRONG_AFTER_RE = re.compile("|".join(map(re.escape, STRONG_AFTER)), re.IGNORECASE)
_WEAK_RE = re.compile(r"\b(" + "|".join(map(re.escape, WEAK)) + r")\b", re.IGNORECASE)
_NEGATIVE_RE = re.compile("|".join(map(re.escape, NEGATIVE)), re.IGNORECASE)

# Vùng không bao giờ chứa OTP - bị xoá trắng nhưng GIỮ NGUYÊN độ dài để ngữ
# cảnh hai bên các dãy số khác không bị xê dịch.
_MASK_RES = [
    re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE),
    # Cả link không có scheme: "example.com/t/483921" vẫn là URL.
    re.compile(r"\b[\w-]+(\.[\w-]+)*\.(com|net|org|io|co|vn|me|app|link)/\S*", re.IGNORECASE),
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]?\d{0,2}:?\d{0,2}:?\d{0,2}\b"),
    re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?\b", re.IGNORECASE),
    re.compile(r"[$€£¥]\s?\d[\d,.]*|\b\d[\d,.]*\s?(usd|eur|vnd|đ)\b", re.IGNORECASE),
]
_TOKEN_CHARS = set("0123456789+-/:.,()")
_SENTENCE = re.compile(r"[\n.;!?]")
CONTEXT = 40
NEAR = 14


@dataclass
class Candidate:
    code: str
    confidence: float
    why: str


def _mask(text: str) -> str:
    for pattern in _MASK_RES:
        text = pattern.sub(lambda m: "\x00" * len(m.group(0)), text)
    return text


def _part_of_bigger_number(text: str, start: int, end: int) -> bool:
    """`4839` nằm trong `48392105` thì không phải mã."""
    left, right = start, end
    while left > 0 and text[left - 1] in _TOKEN_CHARS:
        left -= 1
    while right < len(text) and text[right] in _TOKEN_CHARS:
        right += 1
    digits = sum(c.isdigit() for c in text[left:right])
    return digits > (end - start)


def extract_code(
    text: str,
    min_len: int = 4,
    max_len: int = 8,
    min_confidence: float = 0.6,
) -> Candidate | None:
    """Trả về ứng viên ĐỦ TỰ TIN, hoặc None.

    Ngưỡng mặc định 0.6 loại thẳng dãy số không có ngữ cảnh nào (0.55): thà
    không trả mã còn hơn trả nhầm số đơn hàng rồi agent điền vào form.
    """
    if not text:
        return None
    masked = _mask(text)
    digits = re.compile(rf"\d{{{min_len},{max_len}}}")
    found: list[Candidate] = []

    for match in digits.finditer(masked):
        if _part_of_bigger_number(masked, match.start(), match.end()):
            continue
        window_before = masked[max(0, match.start() - CONTEXT):match.start()]
        before = _SENTENCE.split(window_before)[-1]
        after = _SENTENCE.split(masked[match.end():match.end() + CONTEXT])[0]

        # Từ khoá phủ định chỉ loại khi nằm CÙNG CÂU với dãy số, nên
        # "Order shipped. Your code is 483921." vẫn nhận đúng mã.
        if _NEGATIVE_RE.search(before) or _NEGATIVE_RE.search(after[:NEAR]):
            continue

        if _STRONG_BEFORE_RE.search(before):
            found.append(Candidate(match.group(0), 0.97, "ngữ cảnh trước"))
        elif _STRONG_AFTER_RE.search(after):
            found.append(Candidate(match.group(0), 0.95, "ngữ cảnh sau"))
        elif _WEAK_RE.search(before) or _WEAK_RE.search(after[:NEAR]):
            found.append(Candidate(match.group(0), 0.80, "ngữ cảnh yếu"))
        else:
            found.append(Candidate(match.group(0), 0.55, "không ngữ cảnh"))

    if not found:
        return None
    found.sort(key=lambda c: -c.confidence)
    best = found[0]

    # Hai ứng viên mạnh ngang nhau nhưng khác số: không đoán bừa.
    rivals = [c for c in found[1:] if c.code != best.code and best.confidence - c.confidence < 0.05]
    if rivals:
        best = Candidate(best.code, round(best.confidence - 0.3, 2), "mơ hồ")

    return best if best.confidence >= min_confidence else None
