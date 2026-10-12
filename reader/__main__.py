"""Chạy giao diện: `uv run python -m reader` rồi mở http://127.0.0.1:5678

Cấu hình đọc từ biến môi trường và từ `.env` ở gốc dự án (xem
`reader/config.py`). Trên server, `./setup.sh` sinh `.env` và unit systemd.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os

import uvicorn

from reader.config import ENV_FILE, Settings, has_display, load_env_file
from reader.server import create_app

logger = logging.getLogger("reader")


def main() -> None:
    loaded_env = load_env_file()
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description="Dán email Outlook, nhận mã OTP.")
    parser.add_argument("--host", default=settings.host,
                        help="0.0.0.0 để máy khác gọi được (mặc định: chỉ máy này)")
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--token", default=None,
                        help="khoá truy cập bạn tự đặt; không có thì lấy "
                             "READER_TOKEN, không có nữa thì trang mở cho "
                             "mọi người. Lưu ý: gõ ở đây thì token hiện trong "
                             "`ps`, trên máy nhiều người dùng nên dùng "
                             "READER_TOKEN")
    parser.add_argument("--check", action="store_true",
                        help="thử mở trình duyệt rồi thoát, in ra lỗi thật "
                             "nếu không mở được (dùng khi lượt lấy mã kẹt ở "
                             "'đang mở trình duyệt')")
    parser.add_argument("--headless", action="store_true",
                        help="không hiện cửa sổ trình duyệt (gặp 2FA thì bạn "
                             "không còn chỗ nào để xử lý)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="log chi tiết (DEBUG): từng nhịp poll, số mail đã "
                             "xem, mỗi lần tải lại trang. Hoặc đặt "
                             "READER_LOG_LEVEL=DEBUG")
    args = parser.parse_args()

    # Mức log: --verbose > READER_LOG_LEVEL > INFO. Để bạn tự theo dõi sâu khi
    # cần mà không phải sửa code; mặc định vẫn gọn.
    level_name = os.getenv("READER_LOG_LEVEL", "").strip().upper()
    level = logging.DEBUG if args.verbose else getattr(
        logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.headless:
        settings = dataclasses.replace(settings, headless=True)
    if args.token is not None:
        settings = dataclasses.replace(settings, token=args.token.strip())

    if loaded_env:
        logger.info("đọc cấu hình từ %s", ENV_FILE)
        if ENV_FILE.stat().st_mode & 0o077:
            logger.warning("%s đọc được bởi người khác trên máy - nó mang token "
                           "và mật khẩu: chmod 600 %s", ENV_FILE, ENV_FILE)
    logger.info(
        "nhịp chạy: poll %ss, tải lại %ss, hạn mỗi lượt %ss, hạn đăng nhập %ss; "
        "headless=%s, log=%s",
        settings.poll_seconds, settings.refresh_seconds,
        settings.timeout_seconds, settings.login_timeout_seconds,
        settings.headless, logging.getLevelName(level),
    )

    if settings.headless and not has_display():
        logger.info("máy không có màn hình nên chạy headless - gặp 2FA hay "
                    "CAPTCHA là tắc, không có cửa sổ nào cho người xử lý")
    if args.host not in ("127.0.0.1", "localhost", "::1") and not settings.token:
        # Không tự từ chối chạy - đôi khi lớp chặn nằm ở tường lửa hay VPN, và
        # ở đó thì thêm token chỉ là phiền. Nhưng phải nói rõ một lần.
        logger.warning(
            "đang nghe trên %s mà KHÔNG có READER_TOKEN: ai dò trúng cổng cũng "
            "dán được tài khoản và đọc được mã. Đặt READER_TOKEN=... rồi mở "
            "trang bằng ?token=...", args.host,
        )

    # In cả token vào địa chỉ: nó do người chạy đặt, hiện ngay trên màn hình
    # của họ, và không in ra thì mở trang bằng gì. Đây là `print` chứ không
    # phải `logger`: log có thể bị gom về một chỗ khác.
    if args.check:
        raise SystemExit(0 if _check(settings) else 1)

    diachi = f"http://{args.host}:{args.port}/"
    if settings.token:
        diachi += f"?token={settings.token}"
    # flush=True: ghi ra file hay qua systemd thì stdout là buffer theo khối,
    # và dòng này mất hẳn nếu tiến trình bị kết thúc trước khi buffer đầy.
    print(f"Mở {diachi}", flush=True)
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="info")


def _check(settings: Settings) -> bool:
    """Mở trình duyệt đúng như một lượt lấy mã mở, rồi đóng.

    Lượt lấy mã kẹt ở "đang mở trình duyệt" nghĩa là nó kẹt ở đây, mà lỗi thật
    thì nằm trong log của luồng nền. Chạy riêng ra thì nó hiện thẳng ra màn
    hình, kèm câu gợi ý cho hai thứ hay thiếu nhất trên server.
    """
    from playwright.sync_api import sync_playwright

    from reader import proxy as proxy_mo
    from reader.browser import launch_persistent

    kenh = settings.browser_channel or "(Chromium của Playwright)"
    try:
        proxy = proxy_mo.parse(settings.proxy_url)
    except ValueError as exc:
        print(f"READER_PROXY sai: {exc}", flush=True)
        return False
    print(f"kênh trình duyệt: {kenh}\nheadless: {settings.headless}\n"
          f"{proxy_mo.describe(proxy)}", flush=True)
    profile = settings.profiles_dir / ".thu-trinh-duyet"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            context = launch_persistent(
                pw, user_data_dir=str(profile),
                channel=settings.browser_channel or None,
                headless=settings.headless, proxy=proxy,
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(settings.inbox_url, wait_until="domcontentloaded", timeout=60000)
            print(f"mở được, đang ở: {page.url[:90]}", flush=True)
            context.close()
        return True
    except Exception as exc:
        loi = str(exc)
        print(f"KHÔNG mở được trình duyệt:\n{loi[:600]}", flush=True)
        thap = loi.lower()
        if ("channel" in thap or "not found" in thap
                or "executable doesn" in thap or "install" in thap):
            print("\n-> Thiếu trình duyệt. Server thường không có Google Chrome:\n"
                  "   chạy với READER_BROWSER_CHANNEL= (để trống) để dùng Chromium\n"
                  "   của Playwright, và cài nó bằng:\n"
                  "   uv run playwright install --with-deps chromium", flush=True)
        elif ("shared librar" in thap or "error while loading" in thap
              or "libn" in thap):
            print("\n-> Thiếu thư viện hệ thống cho Chromium:\n"
                  "   uv run playwright install --with-deps chromium", flush=True)
        elif "err_proxy" in thap or "err_tunnel" in thap:
            print("\n-> Trình duyệt mở được nhưng không đi qua được proxy:\n"
                  "   kiểm READER_PROXY, rồi ./setup.sh --check để curl thử "
                  "cùng proxy đó", flush=True)
        elif not settings.headless:
            print("\n-> Máy không có màn hình thì phải chạy headless:\n"
                  "   thêm --headless, hoặc READER_HEADLESS=true", flush=True)
        return False


if __name__ == "__main__":
    main()
