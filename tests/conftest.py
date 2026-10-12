from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from reader.config import Settings

PAGES = Path(__file__).resolve().parent.parent / "reader" / "testpages"


@pytest.fixture(scope="session")
def playwright():
    """Một instance dùng chung: mở hai cái trong cùng vòng lặp là lỗi."""
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(playwright):
    b = playwright.chromium.launch()
    yield b
    b.close()


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Nhịp ngắn, nhưng login_timeout đủ cho cả luồng đăng nhập nhiều bước:
    mỗi màn hình (email, mật khẩu, 'quick note', 'stay signed in'...) có một
    nhịp chờ ~2s cố định trong mail_login, cộng lại cần hơn 20s - để ngắn quá
    thì luồng đăng nhập thật chưa kịp xong đã bị cắt."""
    return dataclasses.replace(
        Settings(),
        profiles_dir=tmp_path / "profiles",
        headless=True,
        poll_seconds=1,
        refresh_seconds=60,
        timeout_seconds=50,
        login_timeout_seconds=40,
    )
