"""Ba đường của giao diện: tạo lượt, hỏi trạng thái, dừng.

Không mở trình duyệt nào: `fetch.run` được thay bằng hàm giả, vì phần đang kiểm
ở đây là điều phối - đọc hộp thư thật đã có test riêng (tests/test_fetch.py).
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from reader.fetch import Result
from reader.outlook import Hit
from reader.server import create_app


@pytest.fixture
def client(settings, monkeypatch):
    goi = []

    def fake_run(email, password, cfg, report, should_stop=None, sign_out_after=False):
        goi.append({"email": email, "password": password,
                    "sign_out_after": sign_out_after})
        report("đang đọc hộp thư")
        return Result(hit=Hit("483921", "ngữ cảnh trước", "dòng xem trước", "TikTok"))

    monkeypatch.setattr("reader.jobs.run", fake_run)
    with TestClient(create_app(settings)) as client:
        client.goi = goi
        yield client


def _wait(client, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/otp/{job_id}").json()
        if job["done"]:
            return job
        time.sleep(0.05)
    raise AssertionError("lượt không xong trong hạn")


def test_dan_vao_roi_nhan_ma(client):
    res = client.post("/api/otp", json={"account": "ten@outlook.com|MatKhau123"})
    assert res.status_code == 200
    job = _wait(client, res.json()["id"])
    assert job["code"] == "483921"
    assert job["status"] == "đã có mã"
    assert job["email"] == "ten@outlook.com"
    assert client.goi[0]["password"] == "MatKhau123"


def test_trang_chu_mo_duoc(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Lấy mã" in res.text


def test_dan_sai_thi_bao_ngay_khong_mo_trinh_duyet(client):
    res = client.post("/api/otp", json={"account": "khong-co-email"})
    assert res.status_code == 400
    assert "email" in res.json()["detail"]
    assert client.goi == []


def test_mat_khau_khong_lot_ra_api(client):
    res = client.post("/api/otp", json={"account": "ten@outlook.com|MatKhau123"})
    job = _wait(client, res.json()["id"])
    assert "MatKhau123" not in res.text
    assert "MatKhau123" not in client.get("/api/jobs").text
    assert "password" not in job


def test_khong_hoi_id_la(client):
    assert client.get("/api/otp/khong-co-that").status_code == 404


def test_cung_email_khong_mo_hai_trinh_duyet(settings, monkeypatch):
    """Hai lượt cùng email là hai Chromium cùng một profile - cái thứ hai không
    khởi động được. Lượt sau phải nhận lại đúng lượt đang chạy."""
    tha = threading.Event()

    def fake_run(email, password, cfg, report, should_stop=None, sign_out_after=False):
        report("đang đọc hộp thư")
        tha.wait(5)
        return Result(hit=Hit("483921", "ngữ cảnh trước", "dòng xem trước", ""))

    monkeypatch.setattr("reader.jobs.run", fake_run)
    with TestClient(create_app(settings)) as client:
        body = {"account": "ten@outlook.com|MatKhau123"}
        mot = client.post("/api/otp", json=body).json()
        hai = client.post("/api/otp", json=body).json()
        assert mot["id"] == hai["id"]
        tha.set()
        _wait(client, mot["id"])


def test_bam_dung_thi_lenh_di_toi_luong_lam_viec(settings, monkeypatch):
    def fake_run(email, password, cfg, report, should_stop=None, sign_out_after=False):
        report("đang đọc hộp thư")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if should_stop():
                return Result(error="bạn đã dừng")
            time.sleep(0.05)
        return Result(error="hết giờ")

    monkeypatch.setattr("reader.jobs.run", fake_run)
    with TestClient(create_app(settings)) as client:
        job_id = client.post("/api/otp", json={"account": "ten@outlook.com|x"}).json()["id"]
        assert client.post(f"/api/otp/{job_id}/stop").status_code == 200
        job = _wait(client, job_id)
        assert job["error"] == "bạn đã dừng"
        assert job["status"] == "không lấy được"
        # Lượt đã xong rồi thì không dừng được nữa.
        assert client.post(f"/api/otp/{job_id}/stop").status_code == 404


def test_khong_thay_ma_thi_noi_ro_la_het_gio(settings, monkeypatch):
    monkeypatch.setattr("reader.jobs.run",
                        lambda *a, **k: Result())
    with TestClient(create_app(settings)) as client:
        job_id = client.post("/api/otp", json={"account": "ten@outlook.com|x"}).json()["id"]
        job = _wait(client, job_id)
        assert job["code"] is None
        assert "không thấy mã nào" in job["error"]
