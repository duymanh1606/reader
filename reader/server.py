"""Giao diện web: dán email, nhận mã.

Ba đường duy nhất: tạo lượt, hỏi trạng thái, dừng lượt. Trang web chỉ là một
file HTML tĩnh ngay cạnh đây.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from reader.account import BadAccount, parse
from reader.config import Settings
from reader.jobs import Jobs

logger = logging.getLogger(__name__)

WEB_PAGE = Path(__file__).resolve().parent / "web.html"


class StartRequest(BaseModel):
    # Một dòng dán vào: "mail@outlook.com|matkhau". Không tách sẵn hai ô trên
    # giao diện vì thứ người ta có trong tay luôn là một dòng như thế.
    account: str
    sign_out_after: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    jobs = Jobs(settings)
    app = FastAPI(title="reader", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.jobs = jobs

    @app.get("/")
    def trang_chu() -> FileResponse:
        return FileResponse(WEB_PAGE)

    @app.post("/api/otp")
    def start(body: StartRequest) -> JSONResponse:
        try:
            account = parse(body.account)
        except BadAccount as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        job = jobs.start(account.email, account.password, body.sign_out_after)
        return JSONResponse(job.as_dict())

    @app.get("/api/otp/{job_id}")
    def status(job_id: str) -> JSONResponse:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="không có lượt nào mang id đó")
        return JSONResponse(job.as_dict())

    @app.post("/api/otp/{job_id}/stop")
    def stop(job_id: str) -> JSONResponse:
        if not jobs.stop(job_id):
            raise HTTPException(status_code=404, detail="lượt đó không còn chạy")
        return JSONResponse({"ok": True})

    @app.get("/api/jobs")
    def listing() -> JSONResponse:
        return JSONResponse({"jobs": jobs.listing()})

    return app


app = create_app()
