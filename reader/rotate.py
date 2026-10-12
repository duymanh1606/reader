"""Đổi IP proxy khi IP dân cư đứng sau nó chết.

IP dân cư là máy của người thật: tắt máy là IP mất, và proxy (9proxy...) vẫn
nhận kết nối nhưng không mở được đường ra - Chromium báo
ERR_TUNNEL_CONNECTION_FAILED, curl thấy 502. Không ai ngồi trước server để gán
IP khác vào cổng, nên reader tự chạy lệnh đổi IP mà bạn khai trong
READER_PROXY_ROTATE, kiểm IP mới đi ra được, rồi cho lượt chạy lại một lần.

Lệnh đổi IP là của nhà cung cấp, reader không biết gì về nó ngoài mã thoát:
    READER_PROXY_ROTATE=9proxy proxy -c VN -p 60000
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)

# Lỗi của Chromium nghĩa là "tới được proxy nhưng proxy không có đường ra".
# KHÔNG gồm ERR_PROXY_CONNECTION_FAILED: đó là không tới được chính proxy
# (daemon chết, sai cổng) - đổi IP không chữa được, chỉ tốn một lượt IP.
DEAD_MARKERS = (
    "err_tunnel_connection_failed",
    "err_socks_connection_failed",
)

# Lệnh đổi IP chạy xong mà IP mới chưa ra được thì thử lại mấy lần.
ROTATE_TRIES = 3
CHECK_URL = "https://api.ipify.org"


# Microsoft chặn đăng nhập bằng mật khẩu THEO RỦI RO khi IP proxy bẩn/bị gắn cờ
# ("Password sign-in isn't available", hoặc cứ gõ đúng mật khẩu mà vẫn bị hỏi
# lại). IP sạch thường qua được, nên cũng đổi IP rồi thử lại như khi IP chết.
# Dấu này do reader.mail_login đặt vào cuối thông báo lỗi (ROTATE_HINT).
RISK_BLOCK_MARKERS = ("password sign-in isn", "cần đổi ip sạch rồi thử lại")


def proxy_dead(error: str | None) -> bool:
    """Lỗi của một lượt có phải do IP sau proxy đã chết không?"""
    text = (error or "").lower()
    return any(marker in text for marker in DEAD_MARKERS)


def risk_blocked(error: str | None) -> bool:
    """Lỗi có phải do Microsoft chặn mật khẩu theo rủi ro của IP không?"""
    text = (error or "").lower()
    return any(marker in text for marker in RISK_BLOCK_MARKERS)


def should_rotate(error: str | None) -> bool:
    """Lỗi này có đáng đổi IP rồi chạy lại không? (IP chết, hoặc bị chặn theo IP)"""
    return proxy_dead(error) or risk_blocked(error)


def exit_ip(proxy_url: str, timeout: float = 15) -> str | None:
    """IP mà bên ngoài nhìn thấy khi đi qua proxy này. None nếu không ra được.

    Chỉ kiểm được proxy HTTP (urllib không nói SOCKS); proxy SOCKS thì trả ""
    - nghĩa là "không biết", người gọi coi như được.
    """
    if not proxy_url.lower().startswith(("http://", "https://")) and "://" in proxy_url:
        return ""
    url = proxy_url if "://" in proxy_url else "http://" + proxy_url
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": url, "https": url})
    )
    try:
        with opener.open(CHECK_URL, timeout=timeout) as res:
            return res.read(64).decode("ascii", "replace").strip() or None
    except Exception as exc:
        logger.debug("kiểm IP qua proxy không xong: %s", exc)
        return None


class Rotator:
    """Đổi IP, dùng chung cho mọi lượt. Có khoá: năm lượt cùng đổ vì một IP
    chết thì chỉ đổi một lần, bốn lượt kia dùng luôn IP mới."""

    def __init__(self, command: str, proxy_url: str):
        self.command = command.strip()
        self.proxy_url = proxy_url
        self._lock = threading.Lock()
        self._rotated_at = 0.0          # time.monotonic() lần đổi xong gần nhất

    @property
    def enabled(self) -> bool:
        return bool(self.command and self.proxy_url)

    def rotate(self, failed_at: float) -> str | None:
        """Gán IP mới vào proxy. Trả IP mới ("" nếu không kiểm được), None nếu
        không đổi được.

        `failed_at`: lúc (monotonic) lượt gọi thấy proxy chết. Có lượt khác đã
        đổi xong SAU mốc đó thì không đổi nữa - IP đang dùng đã là IP mới.
        """
        if not self.enabled:
            return None
        with self._lock:
            if self._rotated_at > failed_at:
                logger.info("proxy: lượt khác vừa đổi IP, dùng luôn")
                return ""
            for lan in range(1, ROTATE_TRIES + 1):
                if not self._run_command():
                    continue
                ip = exit_ip(self.proxy_url)
                if ip is not None:
                    self._rotated_at = time.monotonic()
                    logger.info("proxy: đã đổi IP (lần %d) - đi ra bằng %s",
                                lan, ip or "(không kiểm được với SOCKS)")
                    return ip
                logger.warning("proxy: đổi IP lần %d xong nhưng vẫn không ra "
                               "được Internet", lan)
            logger.error("proxy: thử đổi IP %d lần đều không được", ROTATE_TRIES)
            return None

    def _run_command(self) -> bool:
        logger.info("proxy: IP chết, chạy: %s", self.command)
        try:
            done = subprocess.run(
                shlex.split(self.command), capture_output=True, text=True,
                timeout=90, stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.error("proxy: không chạy được lệnh đổi IP: %s", exc)
            return False
        out = (done.stdout + done.stderr).strip()
        if done.returncode != 0:
            logger.error("proxy: lệnh đổi IP thoát mã %d: %s",
                         done.returncode, out[:300])
            return False
        logger.debug("proxy: lệnh đổi IP in ra: %s", out[:300])
        return True
