"""Phép tìm phần tử dùng chung, không phụ thuộc trang nào."""

from __future__ import annotations


def first_visible(page, selectors, limit: int = 5):
    """Phần tử ĐANG HIỆN đầu tiên khớp một trong các selector.

    Phải soi từng phần tử khớp, không chỉ cái đầu: trang đăng nhập của
    Microsoft giữ sẵn cả form email lẫn form mật khẩu trong DOM, cái không
    dùng thì ẩn - chỉ xét `.first` là bỏ sót đúng cái đang hiện.
    """
    for selector in selectors:
        items = page.locator(selector)
        try:
            count = min(items.count(), limit)
        except Exception:
            continue
        for index in range(count):
            item = items.nth(index)
            try:
                if item.is_visible():
                    return item
            except Exception:
                continue
    return None


def first_visible_by_role(page, names, roles=("button", "link"), limit: int = 5):
    """Nút/link ĐANG HIỆN đầu tiên mang một trong các tên này.

    `names` nhận cả chuỗi (khớp đúng cả tên) lẫn biểu thức chính quy đã biên
    dịch - Playwright bỏ qua `exact` khi tên là regex.

    `page` ở đây có thể là một `Frame`: màn hình thông báo của Microsoft đôi
    khi nằm trong iframe, và `Frame` có đủ `locator` / `get_by_role`.
    """
    for name in names:
        for role in roles:
            items = page.get_by_role(role, name=name, exact=True)
            try:
                count = min(items.count(), limit)
            except Exception:
                continue
            for index in range(count):
                item = items.nth(index)
                try:
                    if item.is_visible():
                        return item
                except Exception:
                    continue
    return None
