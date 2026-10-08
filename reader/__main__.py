"""Chạy giao diện: `uv run python -m reader` rồi mở http://127.0.0.1:8000"""

from __future__ import annotations

import argparse
import dataclasses
import logging

import uvicorn

from reader.config import Settings
from reader.server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Dán email Outlook, nhận mã OTP.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--headless", action="store_true",
                        help="không hiện cửa sổ trình duyệt (gặp 2FA thì bạn "
                             "không còn chỗ nào để xử lý)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    settings = Settings.from_env()
    if args.headless:
        settings = dataclasses.replace(settings, headless=True)

    print(f"Mở http://{args.host}:{args.port}")
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
