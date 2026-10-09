from __future__ import annotations

import os

import pytest

from reader.config import Settings, load_env_file


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """Một bản sao môi trường không có biến READER_ nào, trả lại sau test.

    `load_env_file` ghi thẳng vào `os.environ`; không cô lập thì biến của test
    này rò sang mọi test chạy sau.
    """
    sach = {k: v for k, v in os.environ.items() if not k.startswith("READER_")}
    monkeypatch.setattr(os, "environ", sach)
    return sach


def test_env_file_fills_settings(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# chú thích\n"
        "\n"
        "READER_TOKEN=abc_123\n"
        "export READER_PORT=8080\n"
        "READER_SMTP_PASSWORD='p@ss $khong noi suy'\n"
        'READER_PROXY="http://u:p@h:3128"\n'
        "READER_BROWSER_CHANNEL=         # rỗng = Chromium\n"
        "READER_WEBHOOK_SECRET=pass#123  # chú thích\n"
        "READER_HOST=   # chỉ có chú thích\n"
        "dong hong khong co dau bang\n",
        encoding="utf-8",
    )
    assert load_env_file(path)
    s = Settings.from_env()
    assert s.token == "abc_123"
    assert s.port == 8080
    assert s.smtp_password == "p@ss $khong noi suy"
    assert s.proxy_url == "http://u:p@h:3128"
    assert s.browser_channel == ""
    assert s.webhook_secret == "pass#123"
    assert s.host == "127.0.0.1"         # rỗng thì về mặc định


def test_environment_beats_env_file(tmp_path, env):
    path = tmp_path / ".env"
    path.write_text("READER_PORT=8080\n", encoding="utf-8")
    env["READER_PORT"] = "9000"

    load_env_file(path)
    assert Settings.from_env().port == 9000


def test_missing_env_file_is_fine(tmp_path):
    assert load_env_file(tmp_path / "khong-co") is False


def test_server_defaults_to_playwright_chromium(env):
    """Không màn hình thì gần như chắc chắn không có Google Chrome."""
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    assert Settings.from_env().browser_channel == ""

    env["DISPLAY"] = ":0"
    assert Settings.from_env().browser_channel == "chrome"
