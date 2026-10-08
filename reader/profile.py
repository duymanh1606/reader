"""Thư mục profile trình duyệt cho mỗi hộp thư, và cái khoá của Chromium.

Chromium đặt `SingletonLock` trong thư mục profile để hai tiến trình không cùng
dùng một profile. Lần chạy nào bị giết giữa chừng thì khoá đó nằm lại, và lần
sau Chromium từ chối khởi động với một thông báo khó hiểu.

Khoá là symlink dạng `<hostname>-<pid>`. Pid không còn sống thì khoá là rác và
dọn được an toàn; còn sống thì profile đang thực sự bị dùng, lúc đó ta nói rõ
thay vì xoá bừa.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

LOCK_NAMES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def profile_for(base: str | Path, email: str) -> Path:
    """Thư mục profile riêng cho một hộp thư.

    Mỗi email một profile: phiên của tài khoản trước không nằm lại làm Outlook
    mở sẵn hộp thư của người khác khi chạy email sau. Ký tự không thuộc
    `[a-z0-9._-]` đổi thành `_`.
    """
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in email.strip().lower())
    return Path(base) / (safe or "mac-dinh")


def _owner_pid(lock: Path) -> int | None:
    try:
        target = os.readlink(lock)
    except OSError:
        return None
    _, _, pid = target.rpartition("-")
    try:
        return int(pid)
    except ValueError:
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True            # tồn tại nhưng của người khác
    return True


def locked_by(profile_dir: str | Path) -> int | None:
    """Pid đang giữ profile, hoặc None nếu rảnh / khoá là rác."""
    lock = Path(profile_dir) / "SingletonLock"
    if not lock.is_symlink() and not lock.exists():
        return None
    pid = _owner_pid(lock)
    return pid if pid and _alive(pid) else None


def clear_stale_lock(profile_dir: str | Path) -> bool:
    """Xoá khoá của tiến trình đã chết. True nếu có dọn gì đó.

    Không bao giờ xoá khoá của tiến trình còn sống - làm thế là mời hai
    Chromium cùng ghi vào một profile.
    """
    profile = Path(profile_dir)
    if not profile.exists():
        return False
    if locked_by(profile) is not None:
        return False

    cleaned = False
    for name in LOCK_NAMES:
        path = profile / name
        try:
            if path.is_symlink() or path.exists():
                path.unlink()
                cleaned = True
        except OSError as exc:
            logger.debug("không xoá được %s: %s", path, exc)
    if cleaned:
        logger.info("đã dọn khoá cũ trong %s", profile.name)
    return cleaned


def explain_launch_error(exc: Exception, profile_dir: str | Path) -> str:
    """Biến lỗi khởi động khó hiểu thành câu người đọc được."""
    text = str(exc)
    if "ProcessSingleton" in text or "SingletonLock" in text:
        pid = locked_by(profile_dir)
        if pid:
            return (
                f"profile {Path(profile_dir).name} đang được một Chromium khác dùng "
                f"(pid {pid}). Đóng cửa sổ đó rồi thử lại."
            )
        return (
            f"profile {Path(profile_dir).name} còn khoá cũ. Thử lại là tự dọn, "
            "hoặc xoá tay: rm -f " + str(Path(profile_dir) / "Singleton*")
        )
    return text
