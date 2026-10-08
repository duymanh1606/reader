"""Chạy giao diện: `uv run python -m reader` rồi mở http://127.0.0.1:5678

Trên server, nghe cả ngoài và khoá bằng token bạn tự đặt:

    uv run python -m reader --host 0.0.0.0 --token chuoi-cua-ban

Hoặc qua biến môi trường, nếu không muốn token hiện trong `ps`:

    READER_TOKEN=chuoi-cua-ban uv run python -m reader --host 0.0.0.0
"""

from __future__ import annotations

import argparse
import dataclasses
import logging

import uvicorn

from reader.config import Settings, has_display
from reader.server import create_app

logger = logging.getLogger("reader")


def main() -> None:
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
    parser.add_argument("--headless", action="store_true",
                        help="không hiện cửa sổ trình duyệt (gặp 2FA thì bạn "
                             "không còn chỗ nào để xử lý)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.headless:
        settings = dataclasses.replace(settings, headless=True)
    if args.token is not None:
        settings = dataclasses.replace(settings, token=args.token.strip())

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
    diachi = f"http://{args.host}:{args.port}/"
    if settings.token:
        diachi += f"?token={settings.token}"
    # flush=True: ghi ra file hay qua systemd thì stdout là buffer theo khối,
    # và dòng này mất hẳn nếu tiến trình bị kết thúc trước khi buffer đầy.
    print(f"Mở {diachi}", flush=True)
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
