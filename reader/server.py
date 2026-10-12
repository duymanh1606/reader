"""Giao diện web: dán email, nhận mã.

Ba đường duy nhất: tạo lượt, hỏi trạng thái, dừng lượt. Trang web chỉ là một
file HTML tĩnh ngay cạnh đây.

Khi `READER_TOKEN` được đặt, mọi đường đều phải kèm token - trang này nhận mật
khẩu hộp thư và trả về mã OTP, nên mở nó ra mạng mà không khoá là đưa cả hai
thứ đó cho bất kỳ ai dò trúng cổng.
"""

from __future__ import annotations

import hmac
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from reader.config import Settings
from reader.jobs import Job, Jobs
from reader.webhook import BadWebhook
from reader.webhook import check as check_webhook

logger = logging.getLogger(__name__)

WEB_PAGE = Path(__file__).resolve().parent / "web.html"
# Tên cookie giữ token sau khi mở trang bằng `?token=...`, để mọi lần gọi API
# sau đó không phải đính token vào từng request.
COOKIE = "reader_token"


class StartRequest(BaseModel):
    # Nhận cả một dòng dán `email|matkhau` ngay trong `email` (để trống
    # `password`) - xem `split_account`.
    email: str
    password: str = ""
    sign_out_after: bool = False
    # Có mã thì POST về đây. Không truyền thì dùng READER_WEBHOOK của server.
    webhook: str | None = None
    # Gửi mã về địa chỉ này. Không truyền thì dùng READER_MAIL_TO của server.
    mail_to: str | None = None


class CodeRequest(StartRequest):
    """Một đường, một lần gọi: gửi email và mật khẩu, chờ, nhận mã."""

    # Chờ tối đa bấy nhiêu giây. None thì lấy đúng hạn của một lượt
    # (`timeout_seconds`); lớn hơn hạn ấy cũng vô nghĩa nên bị cắt về.
    wait: float | None = None


def split_account(email: str, password: str = "") -> tuple[str, str]:
    """`email|matkhau` -> (email, matkhau). Cắt ở dấu `|` ĐẦU TIÊN.

    Email không chứa được `|`, còn mật khẩu thì có thể - nên phần sau dấu đầu
    tiên là mật khẩu nguyên vẹn. Có `password` riêng thì nó thắng, và khi đó
    `email` không bị cắt.
    """
    email = (email or "").strip()
    password = password or ""
    if not password and "|" in email:
        email, password = email.split("|", 1)
        # Dòng dán từ danh sách hay dính dấu cách/xuống dòng ở cuối.
        password = password.strip()
    return email.strip().lower(), password


def _start(jobs: Jobs, body: StartRequest) -> Job:
    """Kiểm email và webhook, báo 400 ngay nếu hỏng, rồi mới dựng lượt.

    Kiểm TRƯỚC khi dựng lượt: dựng xong mới phát hiện webhook hỏng là đã mở
    một trình duyệt và đăng nhập một hộp thư cho một lần gọi sai.
    """
    email, password = split_account(body.email, body.password)
    if not email or "@" not in email:
        raise HTTPException(
            status_code=400,
            detail="không thấy địa chỉ email hợp lệ - dán dạng email|matkhau",
        )
    try:
        webhook = check_webhook(body.webhook or "")
    except BadWebhook as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return jobs.start(email, password, body.sign_out_after,
                      webhook, (body.mail_to or "").strip())


def _token_from(request: Request) -> str:
    """Token người gọi đưa, tìm theo thứ tự: header, cookie, rồi query."""
    return (
        request.headers.get("x-reader-token")
        or request.cookies.get(COOKIE)
        or request.query_params.get("token")
        or ""
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    jobs = Jobs(settings)
    app = FastAPI(title="reader", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.jobs = jobs

    def guard(request: Request) -> None:
        """Chặn mọi đường khi token không đúng.

        So bằng `compare_digest`: so bằng `==` thì thời gian so sánh dài ngắn
        theo số ký tự khớp, và một kẻ kiên nhẫn dò được từng ký tự một.
        """
        if not settings.token:
            return
        if not hmac.compare_digest(_token_from(request), settings.token):
            raise HTTPException(status_code=401, detail="thiếu hoặc sai token")

    need_token = [Depends(guard)]

    @app.get("/", dependencies=need_token)
    def trang_chu(request: Request) -> FileResponse:
        # no-store: cập nhật server xong mà trình duyệt vẫn chạy trang cũ
        # trong cache là một kiểu lỗi rất khó lần ra.
        res = FileResponse(WEB_PAGE, headers={"Cache-Control": "no-store"})
        if settings.token and request.query_params.get("token"):
            # Mở trang bằng `?token=...` một lần, rồi cookie lo phần còn lại:
            # trang tự gọi API mà không phải đính token vào từng request, và
            # token không nằm lại trên thanh địa chỉ của mọi lần tải sau.
            res.set_cookie(COOKIE, settings.token, httponly=True,
                           samesite="strict", max_age=7 * 24 * 3600)
        return res

    @app.post("/api/otp", dependencies=need_token)
    def start(body: StartRequest) -> JSONResponse:
        return JSONResponse(_start(jobs, body).as_dict())

    @app.post("/api/code", dependencies=need_token)
    def code(body: CodeRequest) -> JSONResponse:
        """Lấy mã trong MỘT lần gọi: chờ sẵn rồi trả mã.

        Đường hai bước ở trên có lý do của nó - giao diện cần thấy từng bước,
        và một lượt có thể mất vài phút. Nhưng một hệ thống khác gọi sang thì
        chỉ muốn đúng cái mã, nên ở đây gói cả hai bước lại.

        Luôn trả cùng một hình dạng JSON, có `ok` để người gọi chỉ cần đọc một
        trường; mã HTTP nói thêm chuyện gì đã xảy ra:
          200 có mã · 408 hết giờ mà chưa thấy · 409 phải có người làm (2FA,
          CAPTCHA, sai mật khẩu) · 400 chuỗi tài khoản không đọc được.
        """
        job = _start(jobs, body)
        han = settings.timeout_seconds + 15      # +15: còn phần mở/đóng trình duyệt
        jobs.wait(job.id, min(body.wait or han, han))

        data = job.as_dict()
        data["ok"] = bool(job.code)
        if job.code:
            ma = 200
        elif not job.done:
            ma = 408
            data["error"] = data["error"] or f"chờ quá {body.wait or han}s mà chưa xong"
        else:
            ma = 409 if job.blocked else 408
        return JSONResponse(data, status_code=ma)

    @app.get("/api/otp/{job_id}", dependencies=need_token)
    def status(job_id: str) -> JSONResponse:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="không có lượt nào mang id đó")
        return JSONResponse(job.as_dict())

    @app.get("/api/otp/{job_id}/screenshot", dependencies=need_token)
    def screenshot(job_id: str) -> Response:
        """Ảnh màn hình mới nhất của trình duyệt trong lượt đó.

        Đường riêng chứ không nhét vào JSON trạng thái: giao diện hỏi trạng
        thái mỗi giây, mà ảnh thì vài trăm KB.
        """
        anh = jobs.screenshot(job_id)
        if anh is None:
            raise HTTPException(status_code=404, detail="chưa có ảnh nào")
        # no-store: ảnh đổi liên tục dưới cùng một địa chỉ.
        return Response(anh, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    @app.post("/api/otp/{job_id}/stop", dependencies=need_token)
    def stop(job_id: str) -> JSONResponse:
        if not jobs.stop(job_id):
            raise HTTPException(status_code=404, detail="lượt đó không còn chạy")
        return JSONResponse({"ok": True})

    @app.get("/api/jobs", dependencies=need_token)
    def listing() -> JSONResponse:
        return JSONResponse({"jobs": jobs.listing()})

    return app

