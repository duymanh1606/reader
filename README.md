# reader

Nhập email và mật khẩu của một hộp thư Outlook trên giao diện web; agent tự mở
trình duyệt, đăng nhập hộp thư đó, đọc **mã OTP gần nhất** rồi trả mã về giao
diện (và, nếu muốn, bắn về webhook hoặc gửi mail cho bạn).

Không có API hộp thư: agent đọc chữ trên trang Outlook như người đọc, và chấm
điểm từng dãy số theo ngữ cảnh quanh nó (`reader/otp_extract.py`) nên nó không
trả về số đơn hàng hay số điện thoại.

## Chạy trên máy của bạn

```bash
uv sync
uv run playwright install chromium      # chỉ lần đầu
uv run python -m reader                 # rồi mở http://127.0.0.1:5678
```

Nhập email, mật khẩu rồi bấm **Lấy mã**. Để trống mật khẩu cũng được: agent mở
cửa sổ Outlook và chờ bạn đăng nhập một lần — phiên nằm lại trong profile nên
"một lần" là một lần thật.

## Triển khai lên server

Cần `git` và [`uv`](https://docs.astral.sh/uv/). Một lần:

```bash
git clone <repo> ~/reader && cd ~/reader
./setup.sh --service
```

`setup.sh` làm hết, theo thứ tự:

1. `uv sync` và cài Chromium kèm thư viện hệ thống (xin `sudo` công khai nếu cần).
2. Sinh `.env` — hỏi `READER_TOKEN` (bỏ trống là tự sinh) và `READER_PROXY`.
   File mode 600, `.gitignore` đã chặn. **Không bao giờ ghi đè** `.env` đã có.
3. Kiểm tới chỗ chứng minh được: sandbox Chromium, gọi ra Internet qua proxy và
   in IP mà bên ngoài nhìn thấy, rồi mở thử trình duyệt đúng như một lượt thật.
4. `--service`: cài unit systemd `reader` (tự lên lại sau reboot và khi đổ),
   khởi động nó, rồi in địa chỉ kèm token để mở từ máy khác.

Không hỏi gì, cho script: `READER_TOKEN=... READER_PROXY=... ./setup.sh --yes --service`.

Hằng ngày:

```bash
journalctl -u reader -f              # xem log
sudo systemctl restart reader        # sau khi sửa .env
./setup.sh --update                  # git pull + cài lại phụ thuộc + khởi động lại
./setup.sh --check                   # chỉ kiểm, không sửa gì
```

Mọi cấu hình nằm trong **`.env`** — token, proxy, SMTP, webhook; đủ danh sách
biến ở `.env.example` và [bảng Cấu hình](#cấu-hình). reader tự đọc file đó lúc
khởi động, nên `uv run python -m reader`, `--check` và service đọc cùng một chỗ;
unit systemd không mang bí mật nào. Nhớ mở cổng 5678 ở tường lửa / security group.

> Đang chạy bản cũ bằng `chay.sh` + `nohup`? Chạy `./setup.sh --service`: nó
> chuyển các biến trong `chay.sh` sang `.env`, dừng tiến trình `nohup` cũ rồi
> bật service. Kiểm `.env` xong thì `rm chay.sh`.

Những thứ `setup.sh` bắt được mà chạy tay thì chỉ hiện ra sau, dưới dạng triệu
chứng khác:

| Nó báo | Nghĩa là |
|---|---|
| `READER_TOKEN RỖNG` | giao diện mở cho mọi người, mà trang này nhận **mật khẩu hộp thư** |
| `READER_PROXY còn chứa dấu '<'` | placeholder chưa thay bằng token thật |
| `407` / `403` / `503` từ proxy | sai mật khẩu proxy / bị từ chối đích / proxy không có đường ra |
| `không có phản hồi` | không tới được proxy, hoặc IP máy này không được phép |
| `user namespace bị khoá` | Chromium sẽ chạy **không sandbox** — in luôn lệnh sysctl để mở |

### Token

Trang này nhận **mật khẩu hộp thư** và trả về **mã OTP**, nên mở ra mạng thì
phải khoá. Mở `http://<ip>:5678/?token=<token>` **một lần** — token được cất
vào cookie, những lần sau mở `http://<ip>:5678/` là đủ. Gọi API trực tiếp thì
đính header `X-Reader-Token`. Không có token đúng thì mọi đường, kể cả trang
chủ, trả 401. Chạy không token trên `0.0.0.0` vẫn được nhưng log cảnh báo một
dòng — chỉ nên thế khi đã có lớp chặn khác (VPN, tường lửa).

```bash
curl -s localhost:5678/api/jobs -H "X-Reader-Token: $(grep -oP '^READER_TOKEN=\K\S*' .env)"
```

**Khởi động lại là mất hết các lượt đang chạy** (chúng chỉ sống trong bộ nhớ),
kể cả mã đã lấy được. Mã nào cần giữ thì để webhook hoặc mail mang đi ngay lúc
có, đừng dựa vào tab đang mở.

### Lượt kẹt ở `đang mở trình duyệt`

Nghĩa là kẹt ở đúng bước khởi động Chromium, và lỗi thật nằm trong log của luồng
nền. Chạy riêng bước đó ra để nó hiện thẳng:

```bash
uv run python -m reader --check
```

Hai thứ hay thiếu nhất trên server: **Google Chrome** (trên máy không màn hình
reader mặc định dùng Chromium của Playwright, nhưng `.env` đặt
`READER_BROWSER_CHANNEL=chrome` thì sẽ đòi Chrome thật) và **thư viện hệ thống**
cho Chromium (`sudo .venv/bin/playwright install-deps chromium`). `--check` nhận
ra cả hai, cùng lỗi proxy, và nói thẳng phải làm gì.

### Theo dõi log

Mặc định log ở mức `INFO` — vừa đủ để biết mỗi lượt đang ở chặng nào và kết
thúc ra sao. Dòng đầu tiên lúc khởi động in ra nhịp chạy đang dùng:

```
nhịp chạy: poll 5s, tải lại 120s, hạn mỗi lượt 180s, hạn đăng nhập 90s; headless=True, log=INFO
```

Mỗi lần đổi trạng thái có **tổng thời gian đã trôi** và **thời lượng chặng vừa
qua**, rồi mỗi lượt khép lại bằng một dòng tổng kết:

```
[ten@outlook.com] đang đọc hộp thư | +8.4s | chặng 'đang đăng nhập Outlook' 5.1s
[ten@outlook.com] XONG sau 9.2s: có mã (dòng xem trước)
```

Lượt không lấy được hay bị chặn ghi ở mức `WARNING` kèm lý do, nên gom nhanh
các lượt cần xem bằng:

```bash
journalctl -u reader | grep -E "WARNING|XONG"
```

Khi một lượt **đứng hình** và muốn nhìn sâu hơn — từng nhịp poll, số mail đã
xem, mỗi lần tải lại trang, mỗi lần quét danh sách — bật mức `DEBUG`:

```bash
echo READER_LOG_LEVEL=DEBUG >> .env && sudo systemctl restart reader
uv run python -m reader --verbose     # hoặc -v, khi chạy tay
```

```
[ten@outlook.com] vòng #7, còn 142s, đã xem 3 mail, url=https://outlook.live.com/mail/0/
quét 8/23 dòng trên cùng
quét xong: 2 mail nghi là mail mã, chưa rút được mã
```

**Mật khẩu và mã OTP không bao giờ vào log** ở bất kỳ mức nào: dòng tổng kết chỉ
ghi "có mã" cùng nơi tìm thấy (`dòng xem trước` / `nội dung mail`), không ghi con
số. Email hộp thư thì có xuất hiện, nên log vẫn nên giữ kín.

### Nhìn được màn hình của agent trên server

Server không có cửa sổ nào hiện ra, nên mỗi nhịp poll agent **chụp lại màn hình
trình duyệt** và giao diện hiện ngay dưới dòng trạng thái, kèm địa chỉ trang nó
đang đứng. Bấm vào ảnh để mở cỡ thật. Đây là cách duy nhất để biết `cần bạn đăng
nhập` thực ra là 2FA, CAPTCHA, hay mật khẩu sai.

Ảnh nằm ở `GET /api/otp/{id}/screenshot` (JPEG), không đi kèm JSON trạng thái —
trạng thái bị hỏi mỗi giây, nhét ảnh vào đấy là tốn vô ích. **Ảnh có thể chứa
nội dung hộp thư**, kể cả mã OTP, nên nếu mở cổng ra Internet thì đừng bỏ token.

### IP của server là lý do hay gặp nhất khiến lượt nào cũng dừng ở 2FA

Microsoft nhìn IP. Đăng nhập một hộp thư từ IP trung tâm dữ liệu — thứ chưa bao
giờ đăng nhập hộp thư đó — gần như chắc chắn bị hỏi xác minh: "unusual sign-in
activity", gửi mã về số điện thoại hay email phụ. Cũng tài khoản ấy, cũng mật
khẩu ấy, đi qua IP dân cư thì thường vào thẳng. Biểu hiện rất đặc trưng: chạy
ngon trên máy ở nhà, lên server là **lượt nào cũng** dừng ở `cần bạn đăng nhập`
với lý do xác thực hai bước.

Cách chữa: cho trình duyệt đi qua proxy dân cư.

```bash
# trong .env
READER_PROXY=http://user:pass@host:port
```

`./setup.sh --check` gọi thử ra Internet qua proxy đó và in IP thật bên ngoài
thấy; `uv run python -m reader --check` in `qua proxy ...` để chắc trình duyệt
cũng dùng nó.

Nhận cả `socks5://`, và thiếu scheme thì coi là `http://`. Mật khẩu proxy không
vào log.

### Đi ra bằng một IP cố định của riêng bạn (egress-ip-gateway)

Máy có nhiều public IP thì cho reader đi ra bằng **đúng một IP bạn chọn**, tách
khỏi các service khác trên cùng máy, bằng
[egress-ip-gateway](https://mekongai.site/duymanh/egress-ip-gateway) — không
phải sửa code reader, nó chỉ là một proxy HTTP có xác thực:

```bash
# trên máy chạy egw, cấp phát một workspace cho reader:
./deploy/provision-client.sh reader       # in ra token, CHỈ HIỆN MỘT LẦN

# trong .env của reader:
READER_PROXY=http://reader:<TOKEN>@127.0.0.1:3128
```

Cổng **3128** (HTTP CONNECT), không phải 1080: Chromium không gửi được
username/password cho SOCKS5. Quy trình đầy đủ — config, ba lớp kiểm, bảng tra
lỗi theo 407/403/503 — ở
[deploy/reader.md](https://mekongai.site/duymanh/egress-ip-gateway/-/blob/main/deploy/reader.md)
trong repo egw.

**Nó không thay được proxy dân cư.** IP của egw là IP bind trên NIC của máy chủ,
tức vẫn là IP trung tâm dữ liệu, và egw không chain lên proxy khác được. Mà
`READER_PROXY` chỉ nhận **một** giá trị, nên dùng egw là **thay cho** proxy dân
cư chứ không cộng thêm. Hộp thư đang vướng 2FA vì IP datacenter thì egw không
chữa được — egw cho bạn quyền chọn IP nào và log được lượt nào đi IP nào, không
cho bạn uy tín IP.

**Trên server không màn hình, agent tự chạy headless** (không có `DISPLAY`), và
khi đó **gặp 2FA hay CAPTCHA là tắc hẳn**: không có cửa sổ nào cho người xử lý,
lượt đó sẽ báo `cần bạn đăng nhập` rồi hết giờ. Hộp thư nào còn vướng 2FA thì
nên đăng nhập một lần trên máy có màn hình, rồi copy thư mục profile tương ứng
trong `.profiles/` lên server.

## Những gì nó không tự làm

Những màn hình **chỉ để thông báo** trên đường vào hộp thư ("We're updating our
terms", "A quick note about your Microsoft account", "Welcome to the new
Outlook"…) thì agent tự bấm qua — chúng không hỏi gì cả, và không bấm thì nó
ngồi hết hạn ở đấy. Danh sách ấy còn dài ra, nên agent **không kể tên từng màn
hình** mà hỏi ba câu về màn hình đang đứng:

1. **Nó có hỏi gì không?** Thấy ô nhập hay danh sách chọn đang hiện → không bấm,
   vì đó là màn hình đang hỏi (ô "Email" của luồng không-mật-khẩu rơi vào đây).
2. **Chữ trên đó có dính `BLOCKERS` không?** (2FA, CAPTCHA, xác minh qua email
   phụ, đổi mật khẩu, tài khoản bị khoá) → không bấm, kể cả khi màn hình ấy chỉ
   có mỗi cái nút "Next".
3. **Nút có nghĩa "đọc rồi, đi tiếp" không?** Chỉ `Next`, `OK`, `Got it`,
   `Continue`, `Skip`, `Not now`, `Accept`, `Tiếp tục`, `Đồng ý`… — khớp **cả
   tên nút**, không khớp một phần ("OK" khớp một phần là trúng luôn "Book now").
   Không có `Learn more`, `No`, `Cancel`, `Send code`, `Sign out`, `Delete`.
   `Yes` cũng không: một mình nó không nói lên đang đồng ý với cái gì — riêng
   "Stay signed in?" có hàm xử lý riêng.

Qua cả ba thì bấm là an toàn: không gõ gì, không gửi mã đi đâu, cùng lắm là sang
một màn hình mà vòng sau đọc lại từ đầu. Chỉ bấm trên tên miền của Microsoft
(`TRUSTED_HOSTS`), soi cả trong iframe, và tối đa 8 lần một lượt. Luật này dùng
cả lúc đăng nhập lẫn lúc đã vào `outlook.live.com` mà còn bị một hộp thoại chen
trước danh sách mail.

Gặp **xác thực hai bước, CAPTCHA, mật khẩu sai, tài khoản bị khoá** hay yêu cầu
**đổi mật khẩu** thì agent dừng, báo `cần bạn đăng nhập`, và **để nguyên cửa sổ**
cho bạn xử lý; bạn làm xong trong lúc lượt còn hạn thì nó đi tiếp. Nó cũng không
bao giờ thử gõ lại mật khẩu sau khi đã bế tắc một lần — gõ lại nhiều lần chỉ làm
Microsoft khoá tài khoản.

Mật khẩu chỉ được gõ trên đúng tên miền đăng nhập của Microsoft
(`TRUSTED_HOSTS` trong `reader/mail_login.py`); một trang giả mạo ở tên miền khác
không nhận được gì. Nó không vào log, không vào file, và không đi ra `/api/jobs`.

## Cấu hình

Mọi thứ có mặc định dùng được ngay; đổi trong `.env` (hoặc biến môi trường —
biến môi trường thắng `.env`):

| Biến | Mặc định | Nghĩa |
|---|---|---|
| `READER_TOKEN` | rỗng | khoá truy cập; rỗng là ai mở được trang cũng dùng được |
| `READER_HOST` | `127.0.0.1` | `0.0.0.0` để máy khác gọi được |
| `READER_PORT` | `5678` | cổng của giao diện |
| `READER_HEADLESS` | theo máy | mặc định `true` khi máy không có màn hình; `true` thì gặp 2FA bạn không còn chỗ nào để xử lý |
| `READER_PROFILES` | `.profiles` | nơi giữ phiên Outlook, mỗi email một thư mục con |
| `READER_INBOX_URL` | `https://outlook.live.com/mail/0/` | hộp thư cần mở |
| `READER_BROWSER_CHANNEL` | `chrome` nếu có màn hình, rỗng nếu không | rỗng thì dùng Chromium của Playwright |
| `READER_PROXY` | rỗng | `http://user:pass@host:port` — xem phần dưới, trên server gần như bắt buộc |
| `READER_WEBHOOK` | rỗng | có mã thì POST JSON về đây |
| `READER_WEBHOOK_SECRET` | rỗng | đi kèm ở header `X-Reader-Secret` |
| `READER_SMTP_HOST` | rỗng | khai vào là bật gửi mail báo mã |
| `READER_SMTP_PORT` | `587` | `465` thì bọc TLS ngay từ đầu |
| `READER_SMTP_USER` / `READER_SMTP_PASSWORD` | rỗng | tài khoản SMTP; Gmail phải dùng mật khẩu ứng dụng |
| `READER_MAIL_FROM` | `READER_SMTP_USER` | địa chỉ gửi đi |
| `READER_MAIL_TO` | rỗng | địa chỉ nhận mã; rỗng là tắt |
| `READER_POLL_SECONDS` | `5` | nhịp đọc lại danh sách mail |
| `READER_REFRESH_SECONDS` | `120` | nhịp tải lại trang (chỉ là lưới an toàn) |
| `READER_TIMEOUT_SECONDS` | `180` | hạn cho cả một lượt lấy mã |
| `READER_LOGIN_TIMEOUT_SECONDS` | `90` | hạn cho riêng bước đăng nhập |
| `READER_LOG_LEVEL` | `INFO` | `DEBUG` để log chi tiết từng nhịp poll (hoặc cờ `--verbose`) |

## API

### Một lần gọi, nhận thẳng mã

Cho hệ thống khác gọi sang: `POST /api/code` chạy cả lượt rồi mới trả lời.

```bash
curl -X POST http://<ip>:5678/api/code \
     -H 'content-type: application/json' \
     -H 'X-Reader-Token: <token>' \
     -d '{"email": "ten@outlook.com", "password": "MatKhau123"}'
```

```json
{"ok": true, "code": "483921", "email": "ten@outlook.com",
 "subject": "TikTok Your verification code", "where": "dòng xem trước",
 "why": "ngữ cảnh trước", "elapsed": 34, "done": true}
```

Luôn cùng một hình dạng JSON, có `ok` để người gọi chỉ cần đọc một trường; mã
HTTP nói thêm chuyện gì đã xảy ra:

| Mã | Nghĩa |
|---|---|
| 200 | có mã, nằm ở `code` |
| 409 | phải có người làm — 2FA, CAPTCHA, sai mật khẩu; lý do ở `blocked` |
| 408 | hết giờ mà không thấy mã nào |
| 400 | email không hợp lệ, hoặc `webhook` không phải `http(s)://` |
| 401 | thiếu hoặc sai token |

Thêm `"wait": 60` để không chờ lâu hơn thế. Hết `wait` mà chưa xong thì trả 408
với `done: false`, nhưng **lượt vẫn chạy tiếp** ở luồng nền — hỏi lại bằng
`GET /api/otp/{id}` là thấy kết quả, không phải chạy lại từ đầu.

Một lượt có thể mất tới vài phút (mở trình duyệt, đăng nhập, chờ mail tới), nên
phía gọi nhớ đặt timeout đủ dài; mặc định chờ `timeout_seconds + 15` giây.

### Có mã thì tự bắn về chỗ bạn

Thêm `webhook` để không phải ngồi chờ câu trả lời: có mã là server POST một
JSON tới URL của bạn.

```bash
# mặc định cho mọi lượt: trong .env
READER_WEBHOOK=https://cho-cua-ban/hook
READER_WEBHOOK_SECRET=chuoi-bi-mat

# hoặc riêng cho một lần gọi (cái này thắng cái trên)
curl -X POST http://<ip>:5678/api/code -H 'content-type: application/json' \
     -d '{"email": "ten@outlook.com", "password": "MatKhau123", "webhook": "https://cho-khac/hook"}'
```

Gói tin gửi đi:

```json
{"ok": true, "code": "483921", "email": "ten@outlook.com",
 "subject": "TikTok Your verification code", "where": "dòng xem trước",
 "why": "ngữ cảnh trước", "job_id": "6e7fab7fc7ec", "at": 1791451653.86}
```

`READER_WEBHOOK_SECRET` nếu có thì đi kèm ở header `X-Reader-Secret`, để phía
nhận biết gói tin đúng là của bạn chứ không phải của ai đó biết URL.

Ba chỗ đáng biết trước:

* **Chỉ bắn khi CÓ mã.** Lượt hỏng, bế tắc 2FA hay hết giờ thì im — bắn cả
  những lượt đó là biến webhook thành cái chuông kêu suốt ngày mà chẳng ai còn
  nhìn. Muốn biết lượt hỏng thì đọc mã HTTP mà `POST /api/code` trả về.
* **Gửi hỏng không làm đổ lượt.** Mã vẫn nằm trong kết quả và vẫn đọc được
  bằng `GET /api/otp/{id}`; chỗ gửi hỏng chỉ ghi một dòng log.
* **URL chỉ nhận `http(s)://`**, kiểm ngay lúc nhận request — sai thì 400 trước
  khi kịp mở trình duyệt. URL không bao giờ xuất hiện lại trong API, vì query
  string của webhook thường mang sẵn một cái khoá.

### Có mã thì gửi thẳng về hộp thư của bạn

**Mặc định TẮT.** Khai đủ máy chủ SMTP và địa chỉ nhận thì mới bật:

```bash
# trong .env, rồi: sudo systemctl restart reader
READER_SMTP_HOST=smtp.gmail.com
READER_SMTP_PORT=587
READER_SMTP_USER=toi@gmail.com
READER_SMTP_PASSWORD=<mật khẩu ứng dụng, không phải mật khẩu Gmail>
READER_MAIL_TO=toi@gmail.com
```

Thư nhận được có **mã ngay trên tiêu đề** — `483921 - mã OTP của ten@outlook.com`
— vì trên điện thoại thông báo đẩy chỉ hiện tiêu đề, để mã ở đấy là đọc được mà
không phải mở thư. Thân thư có thêm hộp thư nguồn và dòng chủ đề của mail chứa
mã.

Từng lần gọi muốn gửi về một địa chỉ khác thì truyền thêm `mail_to`:

```bash
curl -X POST http://<ip>:5678/api/code -H 'content-type: application/json' \
     -d '{"email": "ten@outlook.com", "password": "MatKhau123", "mail_to": "rieng@vi-du.com"}'
```

Cổng `465` thì bọc TLS ngay từ đầu, `587` thì STARTTLS — đoán theo cổng, không
phải khai thêm cờ. Không khai `READER_SMTP_USER` cũng chạy, miễn là có
`READER_MAIL_FROM` (máy chủ SMTP nội bộ thường không đòi đăng nhập).

Như webhook: **chỉ gửi khi có mã**, và gửi hỏng không làm đổ lượt — mã vẫn nằm
trong kết quả, chỗ hỏng chỉ ghi một dòng log. Tắt lại thì bỏ `READER_SMTP_HOST`
hoặc `READER_MAIL_TO` đi.

Dùng Gmail thì phải là **mật khẩu ứng dụng** (App password, 16 ký tự), bật sau
khi đã bật xác minh hai bước cho tài khoản Google; mật khẩu Gmail thường không
đăng nhập SMTP được.

### Hai bước, cho giao diện

| Đường | Việc |
|---|---|
| `POST /api/otp` `{"email": "...", "password": "...", "sign_out_after": false}` | tạo một lượt, trả về `id` |
| `GET /api/otp/{id}` | trạng thái: `status`, `detail`, `code`, `error`, `done` |
| `POST /api/otp/{id}/stop` | dừng lượt đang chạy |
| `GET /api/jobs` | các lượt gần đây (không chứa mật khẩu) |

Đặt `READER_TOKEN` thì mọi đường trong bảng đều cần token, qua header
`X-Reader-Token`, cookie `reader_token`, hoặc `?token=` trên URL.

Giao diện hỏi `GET /api/otp/{id}` mỗi giây, vì một lượt có thể mất tới vài phút:
Playwright bản sync phải nằm trọn trong một luồng, nên mỗi lượt là một luồng
riêng và kênh duy nhất đi ra là bản ghi trạng thái có khoá (`reader/jobs.py`).

## Mã nguồn

| File | Việc |
|---|---|
| `reader/server.py` + `reader/web.html` | giao diện và ba đường API |
| `reader/jobs.py` | sổ các lượt, mỗi lượt một luồng |
| `reader/fetch.py` | một lượt: mở trình duyệt → đăng nhập → vòng đọc hộp thư |
| `reader/mail_login.py` | máy trạng thái đăng nhập Microsoft (bẫy "không mật khẩu", luật bấm qua thông báo) |
| `reader/outlook.py` | nhận ra trạng thái trang, quét danh sách mail |
| `reader/otp_extract.py` | chấm điểm dãy số để chọn đúng mã |
| `reader/proxy.py` | đọc chuỗi proxy cho trình duyệt |
| `reader/config.py` | đọc `.env` và biến môi trường thành `Settings` |
| `setup.sh` | dựng reader trên server: phụ thuộc, `.env`, kiểm đường ra, systemd |
| `reader/webhook.py` | bắn mã về URL của bạn |
| `reader/mailer.py` | gửi mã về hộp thư của bạn qua SMTP |

## Test

```bash
uv run pytest
```

Chạy **offline hoàn toàn**: mọi request tới `outlook.live.com` / `login.live.com`
bị chặn và trả bằng trang mẫu trong `reader/testpages/`, nên luật nhận dạng và
mọi thứ phụ thuộc URL vẫn đúng như thật. `tests/test_fetch.py` đi hết đường
thật — trang giới thiệu → cổng đăng nhập → màn hình "không mật khẩu" → mật khẩu
→ "We're updating our terms" → "A quick note about your Microsoft account"
(trong iframe) → "Stay signed in?" → hộp thư → mã — nên cả bộ test mất khoảng ba phút.

## Điểm yếu đã biết

1. **Phụ thuộc DOM Outlook.** Microsoft đổi layout là phần quét mù, và biểu hiện
   ra ngoài chỉ là "hết giờ mà không thấy mã" chứ không phải một lỗi rõ ràng.
2. **Không xác minh người gửi.** Mã lấy được là mã trong mail mới nhất trông
   giống mail OTP, bất kể ai gửi.
3. **Quét có ghi, không chỉ đọc.** Mã không nằm ở dòng xem trước thì agent mở
   mail ra, tức là **đánh dấu đã đọc**.
4. **"Gần nhất" là gần nhất trong hộp thư, không phải "mới tới".** Nếu bạn cần mã
   vừa được gửi, hãy bấm Lấy mã **sau** khi dịch vụ kia gửi mail.
