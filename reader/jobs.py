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

from reader.config import Settings
from reader.fetch import Result, run

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
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)

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
            "done": self.done,
            "elapsed": round((self.finished_at or time.time()) - self.started_at),
        }


class Jobs:
    """Sổ các lượt. Mọi lần đọc/ghi đều dưới một khoá."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    # -- giao diện gọi -----------------------------------------------------
    def start(self, email: str, password: str, sign_out_after: bool = False) -> Job:
        """Dựng một lượt mới. Cùng email đang chạy thì trả lại lượt đang chạy.

        Hai lượt cùng email là hai Chromium cùng một thư mục profile - cái thứ
        hai không khởi động được, và lỗi nó in ra chẳng nói gì về nguyên nhân.
        """
        with self._lock:
            self._sweep()
            for job in self._jobs.values():
                if job.email == email and not job.done:
                    return job
            job = Job(id=uuid.uuid4().hex[:12], email=email)
            self._jobs[job.id] = job

        thread = threading.Thread(
            target=self._work, args=(job, password, sign_out_after),
            name=f"reader-{job.email}", daemon=True,
        )
        thread.start()
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

    def listing(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: -j.started_at)
            return [job.as_dict() for job in jobs]

    # -- luồng làm việc ----------------------------------------------------
    def _work(self, job: Job, password: str, sign_out_after: bool) -> None:
        def report(status: str, detail: str = "") -> None:
            with self._lock:
                job.status = status
                job.detail = detail
            logger.info("[%s] %s %s", job.email, status, detail)

        try:
            result = run(job.email, password, self.settings, report,
                         should_stop=job._stop.is_set,
                         sign_out_after=sign_out_after)
        except Exception as exc:                  # pragma: no cover - lưới cuối
            logger.exception("lượt %s đổ", job.id)
            result = Result(error=f"lỗi: {exc}")
        self._finish(job, result)

    def _finish(self, job: Job, result: Result) -> None:
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
            else:
                job.status = "không lấy được"
                job.error = (
                    f"hết {self.settings.timeout_seconds}s mà không thấy mã nào "
                    "trong hộp thư"
                )
                job.detail = job.error

    def _sweep(self) -> None:
        """Dọn lượt đã xong từ lâu. Gọi dưới khoá."""
        cutoff = time.time() - KEEP_SECONDS
        for job_id in [i for i, j in self._jobs.items()
                       if j.finished_at is not None and j.finished_at < cutoff]:
            del self._jobs[job_id]
