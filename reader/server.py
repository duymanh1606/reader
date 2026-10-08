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
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from reader.account import BadAccount, parse
from reader.config import Settings
from reader.jobs import Jobs

logger = logging.getLogger(__name__)

WEB_PAGE = Path(__file__).resolve().parent / "web.html"
# Tên cookie giữ token sau khi mở trang bằng `?token=...`, để mọi lần gọi API
# sau đó không phải đính token vào từng request.
COOKIE = "reader_token"


class StartRequest(BaseModel):
    # Một dòng dán vào: "mail@outlook.com|matkhau". Không tách sẵn hai ô trên
    # giao diện vì thứ người ta có trong tay luôn là một dòng như thế.
    account: str
    sign_out_after: bool = False


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
        res = FileResponse(WEB_PAGE)
        if settings.token and request.query_params.get("token"):
            # Mở trang bằng `?token=...` một lần, rồi cookie lo phần còn lại:
            # trang tự gọi API mà không phải đính token vào từng request, và
            # token không nằm lại trên thanh địa chỉ của mọi lần tải sau.
            res.set_cookie(COOKIE, settings.token, httponly=True,
                           samesite="strict", max_age=7 * 24 * 3600)
        return res

    @app.post("/api/otp", dependencies=need_token)
    def start(body: StartRequest) -> JSONResponse:
        try:
            account = parse(body.account)
        except BadAccount as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        job = jobs.start(account.email, account.password, body.sign_out_after)
        return JSONResponse(job.as_dict())

    @app.get("/api/otp/{job_id}", dependencies=need_token)
    def status(job_id: str) -> JSONResponse:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="không có lượt nào mang id đó")
        return JSONResponse(job.as_dict())

    @app.post("/api/otp/{job_id}/stop", dependencies=need_token)
    def stop(job_id: str) -> JSONResponse:
        if not jobs.stop(job_id):
            raise HTTPException(status_code=404, detail="lượt đó không còn chạy")
        return JSONResponse({"ok": True})

    @app.get("/api/jobs", dependencies=need_token)
    def listing() -> JSONResponse:
        return JSONResponse({"jobs": jobs.listing()})

    return app


app = create_app()
