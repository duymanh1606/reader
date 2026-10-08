"""Mở trình duyệt. Một chỗ duy nhất, để cái quyết định về sandbox nằm một nơi.

Playwright mặc định tắt sandbox của Chromium (`chromium_sandbox=False`), tức là
truyền `--no-sandbox`. Mặc định ấy hợp lý với CI trong container, nơi sandbox
hay không dựng được; nhưng ở đây ta mở trang web thật bằng một profile có phiên
đăng nhập thật, nên tắt lớp cách ly tiến trình là mất hàng rào chính của trình
duyệt. Ta BẬT sandbox, và máy nào không dựng được thì lùi lại chứ không chết.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def launch_persistent(pw, user_data_dir: str, channel: str | None, headless: bool,
                      args: list[str] | None = None, **kwargs):
    chung = dict(user_data_dir=user_data_dir, headless=headless,
                 args=args or [], **kwargs)
    if channel:
        chung["channel"] = channel
    try:
        return pw.chromium.launch_persistent_context(chromium_sandbox=True, **chung)
    except Exception as exc:
        logger.warning(
            "không dựng được sandbox của trình duyệt, chạy không sandbox: %s",
            str(exc).splitlines()[0][:120],
        )
        return pw.chromium.launch_persistent_context(chromium_sandbox=False, **chung)
