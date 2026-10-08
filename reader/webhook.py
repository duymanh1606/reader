"""Có mã thì bắn về một URL do bạn đưa.

Dùng `urllib` của Python chứ không thêm `requests`: một lần POST JSON không
đáng để kéo thêm một thư viện vào.

Gửi hỏng KHÔNG làm đổ lượt lấy mã: mã đã nằm trong kết quả rồi, và `GET
/api/otp/{id}` vẫn đọc được nó. Hỏng thì ghi log, có nói rõ trong `README`.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

TIMEOUT = 10
ALLOWED_SCHEMES = ("http", "https")


class BadWebhook(ValueError):
    """URL webhook không dùng được."""


def check(url: str) -> str:
    """Kiểm URL trước khi nhận. Trả về chính nó, hoặc ném `BadWebhook`.

    Chỉ http/https: `file://` là đọc file trên server, và mấy scheme khác thì
    `urllib` cũng không POST được.
    """
    url = (url or "").strip()
    if not url:
        return ""
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ALLOWED_SCHEMES or not parts.netloc:
        raise BadWebhook(f"webhook phải là http(s)://..., không nhận {url[:60]}")
    return url


def send(url: str, payload: dict, secret: str = "") -> bool:
    """POST JSON tới `url`. Trả True nếu máy chủ kia nhận (2xx).

    `secret` nếu có thì đi kèm ở header `X-Reader-Secret`, để phía nhận biết
    gói tin đúng là của bạn chứ không phải ai đó biết URL.
    """
    if not url:
        return False
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if secret:
        headers["X-Reader-Secret"] = secret
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as res:
            ok = 200 <= res.status < 300
    except urllib.error.HTTPError as exc:
        logger.warning("webhook %s trả %s", _goncho(url), exc.code)
        return False
    except Exception as exc:
        logger.warning("không gửi được webhook %s: %s", _goncho(url), exc)
        return False
    logger.info("đã gửi mã về webhook %s", _goncho(url))
    return ok


def _goncho(url: str) -> str:
    """Chỉ host + đường dẫn cho log: query string hay chứa khoá."""
    parts = urllib.parse.urlparse(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"
