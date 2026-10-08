"""Gửi mã về hộp thư của bạn. Mặc định TẮT cho tới khi khai đủ cấu hình."""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from reader.fetch import Result
from reader.mailer import Mailbox, build, send
from reader.outlook import Hit
from reader.server import create_app

DAY_DU = Mailbox(host="smtp.vi-du.com", port=587, user="toi@vi-du.com",
                 password="bi-mat", to="toi@vi-du.com")


class MaySMTP:
    """Máy chủ SMTP giả: ghi lại đã làm gì, không chạm tới mạng."""

    cuoi: "MaySMTP | None" = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.da_starttls = False
        self.dang_nhap = None
        self.thu = None
        MaySMTP.cuoi = self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.da_starttls = True

    def login(self, user, password):
        self.dang_nhap = (user, password)

    def send_message(self, thu):
        self.thu = thu


@pytest.fixture
def smtp(monkeypatch):
    monkeypatch.setattr("smtplib.SMTP", MaySMTP)
    monkeypatch.setattr("smtplib.SMTP_SSL", MaySMTP)
    MaySMTP.cuoi = None
    return MaySMTP


# -- công tắc --------------------------------------------------------------
@pytest.mark.parametrize("thieu", ["host", "to", "user"])
def test_thieu_cau_hinh_thi_coi_nhu_tat(thieu):
    box = dataclasses.replace(DAY_DU, **{thieu: ""})
    assert box.ready is False


def test_tat_thi_khong_cham_toi_smtp(smtp):
    assert send(Mailbox(), "483921", "ten@outlook.com") is False
    assert smtp.cuoi is None


def test_co_sender_rieng_thi_khong_can_user():
    """Máy chủ SMTP nội bộ thường không đòi đăng nhập."""
    box = Mailbox(host="smtp.noi-bo", user="", sender="reader@noi-bo", to="toi@noi-bo")
    assert box.ready is True


# -- lá thư ----------------------------------------------------------------
def test_ma_nam_tren_tieu_de():
    """Trên điện thoại, thông báo đẩy chỉ hiện tiêu đề - để mã ở đấy là đọc
    được mà không phải mở thư."""
    thu = build(DAY_DU, "483921", "ten@outlook.com", "TikTok Your verification code")
    assert thu["Subject"].startswith("483921")
    assert "ten@outlook.com" in thu["Subject"]


def test_than_thu_co_du_ma_hop_thu_va_mail():
    thu = build(DAY_DU, "483921", "ten@outlook.com", "TikTok mã xác minh")
    than = thu.get_content()
    assert "483921" in than and "ten@outlook.com" in than and "TikTok mã xác minh" in than


def test_gui_toi_dia_chi_cua_rieng_luot_neu_co():
    thu = build(DAY_DU, "483921", "ten@outlook.com", to="khac@vi-du.com")
    assert thu["To"] == "khac@vi-du.com"


# -- gửi -------------------------------------------------------------------
def test_gui_qua_starttls_va_dang_nhap(smtp):
    assert send(DAY_DU, "483921", "ten@outlook.com") is True
    may = smtp.cuoi
    assert (may.host, may.port) == ("smtp.vi-du.com", 587)
    assert may.da_starttls is True
    assert may.dang_nhap == ("toi@vi-du.com", "bi-mat")
    assert "483921" in may.thu["Subject"]


def test_cong_465_thi_boc_tls_ngay_khong_starttls(smtp):
    send(dataclasses.replace(DAY_DU, port=465), "483921", "ten@outlook.com")
    assert smtp.cuoi.da_starttls is False


def test_gui_hong_khong_nem_loi(monkeypatch):
    """Mã đã nằm trong kết quả rồi; gửi hỏng chỉ là thiếu một cái thông báo."""
    def no(*a, **k):
        raise OSError("máy chủ không trả lời")

    monkeypatch.setattr("smtplib.SMTP", no)
    assert send(DAY_DU, "483921", "ten@outlook.com") is False


def test_mat_khau_smtp_khong_lot_vao_log():
    assert "bi-mat" not in repr(DAY_DU)


# -- nối vào lượt lấy mã ---------------------------------------------------
def _app(settings, monkeypatch, result):
    monkeypatch.setattr("reader.jobs.run", lambda *a, **k: result)
    return create_app(settings)


def test_co_ma_thi_gui_mail(settings, monkeypatch, smtp):
    cai_dat = dataclasses.replace(
        settings, smtp_host="smtp.vi-du.com", smtp_user="toi@vi-du.com",
        smtp_password="bi-mat", mail_to="toi@vi-du.com",
    )
    hit = Hit("483921", "ngữ cảnh trước", "dòng xem trước", "TikTok mã xác minh")
    with TestClient(_app(cai_dat, monkeypatch, Result(hit=hit))) as client:
        assert client.post("/api/code",
                           json={"account": "ten@outlook.com|x"}).status_code == 200
    assert "483921" in smtp.cuoi.thu["Subject"]
    assert smtp.cuoi.thu["To"] == "toi@vi-du.com"


def test_khong_co_ma_thi_khong_gui_gi(settings, monkeypatch, smtp):
    cai_dat = dataclasses.replace(
        settings, smtp_host="smtp.vi-du.com", smtp_user="toi@vi-du.com",
        mail_to="toi@vi-du.com",
    )
    with TestClient(_app(cai_dat, monkeypatch, Result(error="hết giờ"))) as client:
        client.post("/api/code", json={"account": "ten@outlook.com|x"})
    assert smtp.cuoi is None


def test_moi_lan_goi_gui_toi_mot_dia_chi_khac_nhau(settings, monkeypatch, smtp):
    cai_dat = dataclasses.replace(
        settings, smtp_host="smtp.vi-du.com", smtp_user="toi@vi-du.com",
        mail_to="mac-dinh@vi-du.com",
    )
    hit = Hit("483921", "ngữ cảnh trước", "dòng xem trước", "")
    with TestClient(_app(cai_dat, monkeypatch, Result(hit=hit))) as client:
        client.post("/api/code", json={"account": "ten@outlook.com|x",
                                       "mail_to": "rieng@vi-du.com"})
    assert smtp.cuoi.thu["To"] == "rieng@vi-du.com"


def test_bam_nut_tren_giao_dien_cung_tu_gui_mail(settings, monkeypatch, smtp):
    """Giao diện đi đường hai bước (`POST /api/otp`), không phải `/api/code` -
    nhưng mail gửi ở chỗ KẾT THÚC lượt, nên cả hai đường đều gửi."""
    cai_dat = dataclasses.replace(
        settings, smtp_host="smtp.vi-du.com", smtp_user="toi@vi-du.com",
        smtp_password="bi-mat", mail_to="toi@vi-du.com",
    )
    hit = Hit("483921", "ngữ cảnh trước", "dòng xem trước", "TikTok mã xác minh")
    with TestClient(_app(cai_dat, monkeypatch, Result(hit=hit))) as client:
        job_id = client.post("/api/otp",
                             json={"account": "ten@outlook.com|x"}).json()["id"]
        for _ in range(50):                      # chờ luồng nền xong
            if client.get(f"/api/otp/{job_id}").json()["done"]:
                break
            import time; time.sleep(0.05)
    assert smtp.cuoi is not None, "bấm nút trên giao diện mà không gửi mail"
    assert "483921" in smtp.cuoi.thu["Subject"]
    assert smtp.cuoi.thu["To"] == "toi@vi-du.com"


def test_chua_khai_smtp_thi_khong_gui_gi_ca(settings, monkeypatch, smtp):
    """Mặc định tắt: có mã cũng không gửi mail nào."""
    hit = Hit("483921", "ngữ cảnh trước", "dòng xem trước", "")
    with TestClient(_app(settings, monkeypatch, Result(hit=hit))) as client:
        client.post("/api/code", json={"account": "ten@outlook.com|x",
                                       "mail_to": "ai-do@vi-du.com"})
    assert smtp.cuoi is None
