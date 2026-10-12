"""Đổi IP proxy khi IP dân cư chết - và chạy lại lượt đúng một lần."""

from __future__ import annotations

import dataclasses
import threading
import time

from fastapi.testclient import TestClient

from reader import rotate
from reader.fetch import Result
from reader.outlook import Hit
from reader.rotate import Rotator, proxy_dead
from reader.server import create_app

CHET = ("lỗi: Page.goto: net::ERR_TUNNEL_CONNECTION_FAILED at "
        "https://outlook.live.com/mail/0/")


def test_nhan_ra_ip_chet():
    assert proxy_dead(CHET)
    assert proxy_dead("net::ERR_SOCKS_CONNECTION_FAILED")
    # Không tới được chính proxy: đổi IP không chữa được.
    assert not proxy_dead("net::ERR_PROXY_CONNECTION_FAILED")
    assert not proxy_dead("sai mật khẩu")
    assert not proxy_dead(None)


def test_khong_khai_lenh_thi_tat():
    assert not Rotator("", "http://127.0.0.1:60000").enabled
    assert not Rotator("true", "").enabled
    assert Rotator("", "http://127.0.0.1:60000").rotate(time.monotonic()) is None


def test_doi_xong_va_ra_duoc_internet(monkeypatch):
    monkeypatch.setattr(rotate, "exit_ip", lambda url, timeout=15: "14.169.1.2")
    assert Rotator("true", "http://127.0.0.1:60000").rotate(time.monotonic()) == "14.169.1.2"


def test_lenh_hong_thi_bao_khong_doi_duoc(monkeypatch):
    monkeypatch.setattr(rotate, "exit_ip", lambda url, timeout=15: "1.2.3.4")
    assert Rotator("false", "http://127.0.0.1:60000").rotate(time.monotonic()) is None
    assert Rotator("lenh-khong-ton-tai-xyz", "http://x:1").rotate(time.monotonic()) is None


def test_doi_roi_van_khong_ra_duoc_thi_thu_lai_roi_thoi(monkeypatch):
    lan = []
    monkeypatch.setattr(rotate, "exit_ip", lambda url, timeout=15: lan.append(1))
    assert Rotator("true", "http://127.0.0.1:60000").rotate(time.monotonic()) is None
    assert len(lan) == rotate.ROTATE_TRIES


def test_nhieu_luot_cung_chet_chi_doi_mot_lan(monkeypatch):
    lan = []

    def fake_ip(url, timeout=15):
        lan.append(1)
        time.sleep(0.2)
        return "5.6.7.8"

    monkeypatch.setattr(rotate, "exit_ip", fake_ip)
    r = Rotator("true", "http://127.0.0.1:60000")
    failed_at = time.monotonic()
    threads = [threading.Thread(target=r.rotate, args=(failed_at,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(lan) == 1


def test_proxy_socks_thi_khong_kiem_duoc_ip():
    assert rotate.exit_ip("socks5://127.0.0.1:60000") == ""


def _client(settings, monkeypatch, ket_qua, doi_ip):
    goi = []

    def fake_run(email, password, cfg, report, should_stop=None,
                 sign_out_after=False, snap=None):
        goi.append(1)
        return ket_qua[len(goi) - 1]

    monkeypatch.setattr("reader.jobs.run", fake_run)
    monkeypatch.setattr(Rotator, "rotate", lambda self, failed_at: doi_ip)
    cfg = dataclasses.replace(settings, proxy_url="http://127.0.0.1:60000",
                              proxy_rotate_cmd="9proxy proxy -c VN -p 60000")
    return TestClient(create_app(cfg)), goi


def _xong(client, body):
    job_id = client.post("/api/otp", json=body).json()["id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/otp/{job_id}").json()
        if job["done"]:
            return job
        time.sleep(0.05)
    raise AssertionError("lượt không xong trong hạn")


def test_ip_chet_thi_doi_ip_roi_chay_lai(settings, monkeypatch):
    client, goi = _client(settings, monkeypatch,
                          [Result(error=CHET), Result(hit=Hit("123456", "", "", ""))],
                          "14.169.1.2")
    with client:
        job = _xong(client, {"email": "ten@outlook.com|mk"})
    assert job["code"] == "123456"
    assert len(goi) == 2


def test_chay_lai_chi_mot_lan(settings, monkeypatch):
    client, goi = _client(settings, monkeypatch,
                          [Result(error=CHET), Result(error=CHET), Result(error=CHET)],
                          "14.169.1.2")
    with client:
        job = _xong(client, {"email": "ten@outlook.com|mk"})
    assert job["error"] and len(goi) == 2


def test_khong_doi_duoc_ip_thi_noi_ro(settings, monkeypatch):
    client, goi = _client(settings, monkeypatch, [Result(error=CHET)], None)
    with client:
        job = _xong(client, {"email": "ten@outlook.com|mk"})
    assert "đổi IP proxy" in job["error"]
    assert len(goi) == 1


def test_loi_khac_thi_khong_doi_ip(settings, monkeypatch):
    client, goi = _client(settings, monkeypatch, [Result(error="sai mật khẩu")], "1.1.1.1")
    with client:
        job = _xong(client, {"email": "ten@outlook.com|mk"})
    assert job["error"] == "sai mật khẩu" and len(goi) == 1
