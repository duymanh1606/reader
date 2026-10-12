"""Proxy cho trình duyệt.

Vì sao cần: Microsoft nhìn IP. Đăng nhập một hộp thư từ IP của trung tâm dữ
liệu - thứ chưa bao giờ đăng nhập hộp thư đó - là gần như chắc chắn bị hỏi xác
minh ("unusual sign-in activity", gửi mã về số điện thoại/email phụ). Cũng tài
khoản ấy, cũng mật khẩu ấy, đi qua một IP dân cư thì thường vào thẳng.

Đây là lý do thường gặp nhất khi agent chạy ngon trên máy ở nhà rồi lên server
là lượt nào cũng dừng ở "xác thực hai bước".
"""

from __future__ import annotations

from urllib.parse import urlparse


def parse(url: str | None) -> dict[str, str] | None:
    """`http://user:pass@host:port` -> dạng Playwright nhận. Rỗng thì None.

    None chứ không phải `{}`: Chromium nhận `--proxy-server=` rỗng là coi như
    có proxy rỗng, và mọi trang đều trắng.
    """
    url = (url or "").strip()
    if not url:
        return None
    if "://" not in url:
        url = "http://" + url
    parts = urlparse(url)
    if not parts.hostname:
        raise ValueError(f"không đọc được proxy: {url[:60]}")
    # Chromium không gửi username/password cho SOCKS: Playwright vẫn nhận cấu
    # hình, rồi mọi trang đổ ERR_PROXY_CONNECTION_FAILED - báo ngay ở đây.
    if parts.scheme.startswith("socks") and parts.username:
        raise ValueError(
            "Chromium không gửi được user/pass cho SOCKS5 - dùng cổng HTTP của "
            "nhà cung cấp proxy (http://user:pass@host:port), hoặc SOCKS5 với "
            "whitelist IP và bỏ user/pass"
        )
    proxy = {"server": f"{parts.scheme}://{parts.hostname}:{parts.port or 8080}"}
    if parts.username:
        proxy["username"] = parts.username
    if parts.password:
        proxy["password"] = parts.password
    return proxy


def describe(proxy: dict[str, str] | None) -> str:
    """Câu để ghi log - KHÔNG kèm mật khẩu proxy."""
    if not proxy:
        return "không qua proxy"
    ai = f"{proxy['username']}@" if proxy.get("username") else ""
    return f"qua proxy {ai}{proxy['server']}"
