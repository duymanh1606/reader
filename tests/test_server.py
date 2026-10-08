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

    def fake_run(email, password, cfg, report, should_stop=None,
                 sign_out_after=False, snap=None):
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

    def fake_run(email, password, cfg, report, should_stop=None,
                 sign_out_after=False, snap=None):
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
    def fake_run(email, password, cfg, report, should_stop=None,
                 sign_out_after=False, snap=None):
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


# -- một đường, một lần gọi ------------------------------------------------
def test_mot_lan_goi_la_co_ma(client):
    """Hệ thống khác gọi sang chỉ muốn đúng cái mã, không muốn hỏi lại mỗi giây."""
    res = client.post("/api/code", json={"account": "ten@outlook.com|MatKhau123"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["code"] == "483921"


def test_bi_chan_boi_2fa_thi_tra_409_kem_ly_do(settings, monkeypatch):
    """409 chứ không phải 408: "phải có người làm" khác hẳn "hết giờ"."""
    def fake_run(email, password, cfg, report, should_stop=None,
                 sign_out_after=False, snap=None):
        report("cần bạn đăng nhập", "Outlook đang hỏi xác thực hai bước")
        return Result()

    monkeypatch.setattr("reader.jobs.run", fake_run)
    with TestClient(create_app(settings)) as client:
        res = client.post("/api/code", json={"account": "ten@outlook.com|x"})
        assert res.status_code == 409
        data = res.json()
        assert data["ok"] is False
        assert "xác thực hai bước" in data["blocked"]
        assert data["status"] == "cần bạn đăng nhập"


def test_khong_thay_ma_thi_tra_408(settings, monkeypatch):
    monkeypatch.setattr("reader.jobs.run", lambda *a, **k: Result())
    with TestClient(create_app(settings)) as client:
        res = client.post("/api/code", json={"account": "ten@outlook.com|x"})
        assert res.status_code == 408
        assert res.json()["ok"] is False


def test_cho_qua_han_thi_tra_408_nhung_luot_van_chay_tiep(settings, monkeypatch):
    tha = threading.Event()

    def fake_run(email, password, cfg, report, should_stop=None,
                 sign_out_after=False, snap=None):
        tha.wait(5)
        return Result(hit=Hit("483921", "ngữ cảnh trước", "dòng xem trước", ""))

    monkeypatch.setattr("reader.jobs.run", fake_run)
    with TestClient(create_app(settings)) as client:
        res = client.post("/api/code",
                          json={"account": "ten@outlook.com|x", "wait": 0.3})
        assert res.status_code == 408
        assert res.json()["done"] is False
        job_id = res.json()["id"]
        tha.set()
        assert _wait(client, job_id)["code"] == "483921"   # vẫn chạy tiếp


def test_dan_sai_thi_khong_mo_trinh_duyet(client):
    res = client.post("/api/code", json={"account": "khong-co-email"})
    assert res.status_code == 400
    assert client.goi == []


# -- ảnh màn hình ----------------------------------------------------------
def test_chua_co_anh_thi_404(client):
    job_id = client.post("/api/otp", json={"account": "ten@outlook.com|x"}).json()["id"]
    _wait(client, job_id)
    assert client.get(f"/api/otp/{job_id}/screenshot").status_code == 404


def test_lay_duoc_anh_man_hinh_cua_luot(settings, monkeypatch):
    """Trên server không có cửa sổ nào để nhìn: ảnh này là mắt của người dùng."""
    anh = b"\xff\xd8\xff-gia-vo-la-jpeg"

    def fake_run(email, password, cfg, report, should_stop=None,
                 sign_out_after=False, snap=None):
        report("đang đăng nhập Outlook")
        snap(anh, "https://login.live.com/login.srf")
        return Result(error="cần bạn đăng nhập")

    monkeypatch.setattr("reader.jobs.run", fake_run)
    with TestClient(create_app(settings)) as client:
        job_id = client.post("/api/otp", json={"account": "ten@outlook.com|x"}).json()["id"]
        job = _wait(client, job_id)
        assert job["shot_at"] is not None
        assert job["page_url"] == "https://login.live.com/login.srf"
        res = client.get(f"/api/otp/{job_id}/screenshot")
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/jpeg"
        assert res.content == anh


def test_anh_khong_di_kem_json_trang_thai(settings, monkeypatch):
    """Giao diện hỏi trạng thái mỗi giây; nhét vài trăm KB base64 vào đấy là
    tốn vô ích."""
    def fake_run(email, password, cfg, report, should_stop=None,
                 sign_out_after=False, snap=None):
        snap(b"x" * 5000, "https://outlook.live.com/mail/0/")
        return Result()

    monkeypatch.setattr("reader.jobs.run", fake_run)
    with TestClient(create_app(settings)) as client:
        job_id = client.post("/api/otp", json={"account": "ten@outlook.com|x"}).json()["id"]
        res = client.get(f"/api/otp/{job_id}")
        assert len(res.content) < 1000
        assert "shot" not in res.json()


# -- khoá truy cập ---------------------------------------------------------
TOKEN = "chuoi-dai-ngau-nhien"


@pytest.fixture
def khoa(settings, monkeypatch):
    """Client của một server CÓ đặt token."""
    import dataclasses

    monkeypatch.setattr(
        "reader.jobs.run",
        lambda *a, **k: Result(hit=Hit("483921", "ngữ cảnh trước", "dòng xem trước", "")),
    )
    with TestClient(create_app(dataclasses.replace(settings, token=TOKEN))) as client:
        yield client


@pytest.mark.parametrize("duong,cach", [
    ("/", "get"),
    ("/api/jobs", "get"),
    ("/api/otp/bat-ky", "get"),
    ("/api/otp", "post"),
    ("/api/otp/bat-ky/stop", "post"),
])
def test_khong_token_thi_khong_duong_nao_di_duoc(khoa, duong, cach):
    goi = getattr(khoa, cach)
    res = goi(duong, json={"account": "ten@outlook.com|x"}) if cach == "post" else goi(duong)
    assert res.status_code == 401


def test_token_sai_cung_khong_di_duoc(khoa):
    res = khoa.get("/api/jobs", headers={"X-Reader-Token": TOKEN + "x"})
    assert res.status_code == 401


def test_token_dung_trong_header_thi_di_duoc(khoa):
    assert khoa.get("/api/jobs", headers={"X-Reader-Token": TOKEN}).status_code == 200


def test_mo_trang_bang_query_roi_cookie_lo_phan_con_lai(khoa):
    """Dán token một lần trên thanh địa chỉ, những lần gọi sau đi bằng cookie -
    trang không phải đính token vào từng request."""
    res = khoa.get(f"/?token={TOKEN}")
    assert res.status_code == 200
    assert khoa.cookies.get("reader_token") == TOKEN
    assert khoa.get("/api/jobs").status_code == 200


def test_khong_dat_token_thi_van_mo_duoc_nhu_cu(client):
    assert client.get("/api/jobs").status_code == 200
