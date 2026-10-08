"""Có mã thì bắn về URL đã khai - và những chỗ không được bắn."""

from __future__ import annotations

import http.server
import json
import threading

import pytest
from fastapi.testclient import TestClient

from reader.fetch import Result
from reader.outlook import Hit
from reader.server import create_app
from reader.webhook import BadWebhook, check, send


@pytest.fixture
def may_chu():
    """Máy chủ nhỏ nhận webhook, giữ lại từng gói tin đã nhận."""
    nhan: list[dict] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        status = 200

        def do_POST(self):
            size = int(self.headers.get("Content-Length", 0))
            nhan.append({
                "body": json.loads(self.rfile.read(size) or b"{}"),
                "path": self.path,
                "secret": self.headers.get("X-Reader-Secret"),
                "content_type": self.headers.get("Content-Type"),
            })
            self.send_response(type(self).status)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.nhan = nhan
    server.Handler = Handler
    server.url = f"http://127.0.0.1:{server.server_address[1]}/hook"
    yield server
    server.shutdown()


# -- kiểm URL --------------------------------------------------------------
def test_chi_nhan_http_va_https():
    assert check("https://vi-du.com/hook?a=1") == "https://vi-du.com/hook?a=1"
    assert check("") == ""
    with pytest.raises(BadWebhook):
        check("file:///etc/passwd")
    with pytest.raises(BadWebhook):
        check("vi-du.com/hook")          # thiếu scheme


# -- gửi thật --------------------------------------------------------------
def test_gui_duoc_goi_tin(may_chu):
    assert send(may_chu.url, {"code": "483921"}, secret="bi-mat") is True
    goi = may_chu.nhan[0]
    assert goi["body"] == {"code": "483921"}
    assert goi["secret"] == "bi-mat"
    assert "application/json" in goi["content_type"]


def test_khong_co_secret_thi_khong_co_header(may_chu):
    send(may_chu.url, {"code": "1"})
    assert may_chu.nhan[0]["secret"] is None


def test_may_chu_kia_tu_choi_thi_tra_false(may_chu):
    may_chu.Handler.status = 500
    try:
        assert send(may_chu.url, {"code": "1"}) is False
    finally:
        may_chu.Handler.status = 200


def test_url_chet_khong_nem_loi():
    """Gửi hỏng không được làm đổ lượt: mã đã nằm trong kết quả rồi."""
    assert send("http://127.0.0.1:1/khong-ai-nghe", {"code": "1"}) is False


# -- nối vào lượt lấy mã ---------------------------------------------------
def _app(settings, monkeypatch, result: Result):
    monkeypatch.setattr("reader.jobs.run",
                        lambda *a, **k: result)
    return TestClient(create_app(settings))


def test_co_ma_thi_ban_ve_webhook_cua_lan_goi(settings, monkeypatch, may_chu):
    hit = Hit("483921", "ngữ cảnh trước", "dòng xem trước", "TikTok mã xác minh")
    with _app(settings, monkeypatch, Result(hit=hit)) as client:
        res = client.post("/api/code", json={"account": "ten@outlook.com|x",
                                             "webhook": may_chu.url})
        assert res.status_code == 200
    goi = may_chu.nhan[0]["body"]
    assert goi["code"] == "483921"
    assert goi["email"] == "ten@outlook.com"
    assert goi["subject"] == "TikTok mã xác minh"
    assert goi["ok"] is True
    assert goi["job_id"] == res.json()["id"]


def test_khong_truyen_thi_dung_webhook_mac_dinh_cua_server(settings, monkeypatch, may_chu):
    import dataclasses

    cai_dat = dataclasses.replace(settings, webhook_url=may_chu.url,
                                  webhook_secret="bi-mat")
    hit = Hit("483921", "ngữ cảnh trước", "dòng xem trước", "")
    monkeypatch.setattr("reader.jobs.run", lambda *a, **k: Result(hit=hit))
    with TestClient(create_app(cai_dat)) as client:
        client.post("/api/code", json={"account": "ten@outlook.com|x"})
    assert may_chu.nhan[0]["body"]["code"] == "483921"
    assert may_chu.nhan[0]["secret"] == "bi-mat"


def test_khong_co_ma_thi_khong_ban_gi_ca(settings, monkeypatch, may_chu):
    """Webhook là để nhận MÃ. Bắn cả những lượt hỏng là biến nó thành cái
    chuông kêu suốt ngày mà chẳng ai còn nhìn."""
    with _app(settings, monkeypatch, Result(error="cần bạn đăng nhập")) as client:
        client.post("/api/code", json={"account": "ten@outlook.com|x",
                                       "webhook": may_chu.url})
    assert may_chu.nhan == []


def test_webhook_hong_thi_bao_400_truoc_khi_mo_trinh_duyet(settings, monkeypatch):
    goi = []
    monkeypatch.setattr("reader.jobs.run",
                        lambda *a, **k: goi.append(1) or Result())
    with TestClient(create_app(settings)) as client:
        res = client.post("/api/code", json={"account": "ten@outlook.com|x",
                                             "webhook": "file:///etc/passwd"})
        assert res.status_code == 400
        assert goi == []


def test_url_webhook_khong_lot_ra_api(settings, monkeypatch, may_chu):
    """Query string của webhook thường mang sẵn một cái khoá."""
    hit = Hit("483921", "ngữ cảnh trước", "dòng xem trước", "")
    with _app(settings, monkeypatch, Result(hit=hit)) as client:
        res = client.post("/api/code", json={"account": "ten@outlook.com|x",
                                             "webhook": may_chu.url + "?key=bi-mat"})
        assert "bi-mat" not in res.text
        assert "bi-mat" not in client.get("/api/jobs").text
