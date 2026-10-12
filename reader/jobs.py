"""Quản lý các lượt lấy mã đang chạy.

Mỗi lượt là một luồng riêng (Playwright sync phải nằm trọn trong một luồng, xem
đầu `reader/fetch.py`), nên giao diện không thể gọi hàm lấy mã rồi đợi: nó tạo
lượt, rồi hỏi trạng thái mỗi giây. Cái list này là kênh duy nhất giữa luồng web
và luồng trình duyệt, và nó có khoá.

Mật khẩu KHÔNG được giữ lại ở đây: nó đi thẳng vào luồng làm việc rồi hết. Một
trang `/api/jobs` lỡ để hở không được phép là chỗ đọc ra mật khẩu.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

from reader import mailer as mailer_mo
from reader import webhook as webhook_mo
from reader.config import Settings
from reader.fetch import Result, run
from reader.rotate import Rotator, proxy_dead

logger = logging.getLogger(__name__)

# Lượt xong bao lâu thì dọn khỏi bộ nhớ.
KEEP_SECONDS = 30 * 60


@dataclass
class Job:
    id: str
    email: str
    status: str = "đang chờ"
    detail: str = ""
    code: str | None = None
    why: str = ""
    where: str = ""
    subject: str = ""
    error: str | None = None
    # Lý do cuối cùng agent phải giao lại cho người (2FA, CAPTCHA, sai mật
    # khẩu). Giữ riêng vì khi lượt kết thúc, `status` bị ghi đè thành "không
    # lấy được" - mà "bế tắc vì 2FA" và "hết giờ chẳng thấy mail nào" là hai
    # chuyện khác hẳn, cả với người đọc lẫn với hệ thống gọi API.
    blocked: str = ""
    # URL bắn mã về khi xong. KHÔNG vào `as_dict`: query string của webhook
    # thường mang sẵn một cái khoá.
    webhook: str = field(default="", repr=False)
    # Địa chỉ nhận mail báo mã, của riêng lượt này. Rỗng thì lấy mặc định của
    # server (`READER_MAIL_TO`).
    mail_to: str = ""
    # Ảnh màn hình mới nhất của trình duyệt, và trang nó đang đứng. Trên server
    # không có cửa sổ nào để nhìn, nên đây là mắt duy nhất của người dùng.
    shot: bytes | None = field(default=None, repr=False)
    shot_at: float | None = None
    page_url: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    # Bật khi lượt xong. Để người gọi API một-đường chờ bằng `wait()` thay vì
    # hỏi lại mỗi 0,2 giây - chờ trên Event thì mã về tới nơi là trả ngay.
    _done: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def done(self) -> bool:
        return self.finished_at is not None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "status": self.status,
            "detail": self.detail,
            "code": self.code,
            "why": self.why,
            "where": self.where,
            "subject": self.subject,
            "error": self.error,
            "blocked": self.blocked,
            "done": self.done,
            # Chỉ thời điểm, không phải ảnh: nhét vài trăm KB base64 vào mỗi
            # lần hỏi trạng thái (mỗi giây) là tốn vô ích. Giao diện lấy ảnh ở
            # đường riêng, và dùng mốc này để biết lúc nào cần lấy lại.
            "shot_at": self.shot_at,
            "page_url": self.page_url,
            "elapsed": round((self.finished_at or time.time()) - self.started_at),
        }


class Jobs:
    """Sổ các lượt. Mọi lần đọc/ghi đều dưới một khoá."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.rotator = Rotator(settings.proxy_rotate_cmd, settings.proxy_url)
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    # -- giao diện gọi -----------------------------------------------------
    def start(self, email: str, password: str, sign_out_after: bool = False,
              webhook: str = "", mail_to: str = "") -> Job:
        """Dựng một lượt mới. Cùng email đang chạy thì trả lại lượt đang chạy.

        Hai lượt cùng email là hai Chromium cùng một thư mục profile - cái thứ
        hai không khởi động được, và lỗi nó in ra chẳng nói gì về nguyên nhân.
        """
        with self._lock:
            self._sweep()
            for job in self._jobs.values():
                if job.email == email and not job.done:
                    return job
            job = Job(id=uuid.uuid4().hex[:12], email=email,
                      webhook=webhook or self.settings.webhook_url,
                      mail_to=mail_to or self.settings.mail_to)
            self._jobs[job.id] = job

        thread = threading.Thread(
            target=self._work, args=(job, password, sign_out_after),
            name=f"reader-{job.email}", daemon=True,
        )
        thread.start()
        return job

    def wait(self, job_id: str, timeout: float) -> Job | None:
        """Chờ tới khi lượt xong, trả về chính nó. None nếu không có lượt ấy.

        Hết `timeout` mà chưa xong thì vẫn trả lượt đó (chưa `done`) - người
        gọi tự quyết, và lượt vẫn chạy tiếp ở luồng nền.
        """
        job = self.get(job_id)
        if job is None:
            return None
        job._done.wait(timeout)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def stop(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.done:
            return False
        job._stop.set()
        return True

    def screenshot(self, job_id: str) -> bytes | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.shot if job else None

    def listing(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: -j.started_at)
            return [job.as_dict() for job in jobs]

    # -- luồng làm việc ----------------------------------------------------
    def _work(self, job: Job, password: str, sign_out_after: bool) -> None:
        # Mốc đo thời gian: mỗi lần `report` đổi trạng thái, ghi lại chặng vừa
        # qua kéo dài bao lâu và đã trôi bao nhiêu giây từ lúc bắt đầu lượt.
        # Dùng `monotonic` chứ không phải `time.time` để chỉnh giờ hệ thống
        # giữa chừng không làm thời lượng âm.
        t0 = time.monotonic()
        stage = {"name": None, "since": t0}

        def report(status: str, detail: str = "") -> None:
            now = time.monotonic()
            with self._lock:
                job.status = status
                job.detail = detail
                if status == "cần bạn đăng nhập":
                    job.blocked = detail or status
            prev = ""
            if stage["name"] is not None and status != stage["name"]:
                prev = f" | chặng '{stage['name']}' {now - stage['since']:.1f}s"
            if status != stage["name"]:
                stage["name"] = status
                stage["since"] = now
            logger.info("[%s] %s %s | +%.1fs%s",
                        job.email, status, detail, now - t0, prev)

        def snap(anh: bytes, url: str) -> None:
            with self._lock:
                job.shot = anh
                job.shot_at = time.time()
                job.page_url = url

        def attempt() -> Result:
            try:
                return run(job.email, password, self.settings, report,
                           should_stop=job._stop.is_set,
                           sign_out_after=sign_out_after, snap=snap)
            except Exception as exc:              # pragma: no cover - lưới cuối
                logger.exception("lượt %s đổ", job.id)
                return Result(error=f"lỗi: {exc}")

        result = attempt()
        # IP dân cư sau proxy chết giữa chừng: đổi IP rồi chạy lại MỘT lần.
        # Một lần thôi - IP mới mà cũng chết ngay thì là chuyện khác, để người xem.
        if (proxy_dead(result.error) and self.rotator.enabled
                and not job._stop.is_set()):
            failed_at = time.monotonic()
            report("đang đổi IP proxy", "IP dân cư cũ đã offline")
            ip = self.rotator.rotate(failed_at)
            if ip is None:
                result = Result(error=f"{result.error}\n-> đã thử đổi IP proxy "
                                      "nhưng không được, xem log của reader")
            else:
                report("đã đổi IP proxy", f"đi ra bằng {ip}" if ip else "")
                result = attempt()
        self._finish(job, result)

    def _finish(self, job: Job, result: Result) -> None:
        self._write_result(job, result)
        # Một dòng tổng kết cho mỗi lượt: kết quả + tổng thời gian chạy. Có mã
        # thì INFO; không lấy được hay bị chặn thì WARNING kèm lý do, để `grep
        # WARNING reader.log` gom đúng các lượt cần xem. KHÔNG log `job.code` -
        # mã OTP không thuộc về file log.
        elapsed = (job.finished_at or time.time()) - job.started_at
        if job.code:
            logger.info("[%s] XONG sau %.1fs: có mã (%s)",
                        job.email, elapsed, job.where or "?")
        else:
            logger.warning("[%s] XONG sau %.1fs: %s - %s",
                           job.email, elapsed, job.status, job.error or "")
        job._done.set()          # sau khi đã ghi xong, không phải trước
        self._call_webhook(job)
        self._send_mail(job)

    def _call_webhook(self, job: Job) -> None:
        """Bắn mã về URL đã khai. Chỉ khi CÓ mã.

        Gọi sau `_done.set()`: người đang chờ ở `POST /api/code` nhận mã ngay,
        không phải đợi thêm một vòng mạng nữa.

        Gửi hỏng không làm đổi kết quả - mã vẫn nằm trong lượt và vẫn đọc được
        bằng `GET /api/otp/{id}`.
        """
        if not job.webhook or not job.code:
            return
        webhook_mo.send(job.webhook, {
            "ok": True,
            "code": job.code,
            "email": job.email,
            "subject": job.subject,
            "where": job.where,
            "why": job.why,
            "job_id": job.id,
            "at": job.finished_at,
        }, self.settings.webhook_secret)

    def _write_result(self, job: Job, result: Result) -> None:
        with self._lock:
            job.finished_at = time.time()
            if result.hit is not None:
                job.code = result.hit.code
                job.why = result.hit.why
                job.where = result.hit.where
                job.subject = result.hit.preview
                job.status = "đã có mã"
                job.detail = ""
            elif result.error:
                job.status = "không lấy được"
                job.error = result.error
                job.detail = result.error
            elif job.blocked:
                job.status = "cần bạn đăng nhập"
                job.error = job.blocked
                job.detail = job.blocked
            else:
                job.status = "không lấy được"
                job.error = (
                    f"hết {self.settings.timeout_seconds}s mà không thấy mã nào "
                    "trong hộp thư"
                )
                job.detail = job.error

    def _send_mail(self, job: Job) -> None:
        """Gửi mã về hộp thư của bạn, nếu đã khai SMTP. Chỉ khi CÓ mã.

        Như webhook: gọi sau `_done.set()` để người đang chờ ở `POST /api/code`
        nhận mã ngay, và gửi hỏng cũng không đổi kết quả.
        """
        if not job.code or not job.mail_to:
            return
        box = self.settings.mailbox
        if not box.ready:
            return
        mailer_mo.send(box, job.code, job.email, job.subject, to=job.mail_to)

    def _sweep(self) -> None:
        """Dọn lượt đã xong từ lâu. Gọi dưới khoá."""
        cutoff = time.time() - KEEP_SECONDS
        for job_id in [i for i, j in self._jobs.items()
                       if j.finished_at is not None and j.finished_at < cutoff]:
            del self._jobs[job_id]
