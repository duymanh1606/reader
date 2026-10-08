# reader

Dán `email|mật khẩu` của một hộp thư Outlook lên giao diện web; agent tự mở
trình duyệt, đăng nhập hộp thư đó, đọc **mã OTP gần nhất** rồi trả mã về giao
diện.

Không có webhook, không có API hộp thư: agent đọc chữ trên trang Outlook như
người đọc, và chấm điểm từng dãy số theo ngữ cảnh quanh nó (`reader/otp_extract.py`)
nên nó không trả về số đơn hàng hay số điện thoại.

## Chạy

```bash
uv sync
uv run playwright install chromium      # chỉ lần đầu
uv run python -m reader                 # rồi mở http://127.0.0.1:5678
```

Dán một dòng rồi bấm **Lấy mã**:

```
ten@outlook.com|MatKhau123
```

Dấu phân cách nhận cả `|`, `:`, tab hay dấu cách; các cột phía sau (refresh
token, client id…) bị bỏ qua. Dán mỗi email mà không có mật khẩu cũng được: agent
mở cửa sổ Outlook và chờ bạn đăng nhập một lần — phiên nằm lại trong profile nên
"một lần" là một lần thật.

## Chạy trên server, mở từ máy khác

```bash
uv sync
uv run playwright install --with-deps chromium     # server trắng thì cần cả --with-deps
uv run python -m reader --host 0.0.0.0 --token chuoi-cua-ban
```

Token là chuỗi **bạn tự đặt**, không có sẵn ở đâu cả. Đặt bằng `--token` như
trên, hoặc bằng `READER_TOKEN=...` nếu không muốn nó hiện trong `ps` (máy nhiều
người dùng). Dù đặt cách nào, dòng đầu tiên server in ra có sẵn cả địa chỉ lẫn
token, chỉ việc copy:

```
Mở http://0.0.0.0:5678/?token=chuoi-cua-ban
```

`--host 0.0.0.0` để máy khác gọi được (mặc định chỉ nghe `127.0.0.1`), và nhớ
mở cổng 5678 ở tường lửa / security group.

Trang này nhận **mật khẩu hộp thư** và trả về **mã OTP**, nên mở ra mạng thì
phải khoá: đặt token, rồi mở `http://<ip>:5678/?token=<token>` **một lần** — token được cất vào cookie, những lần sau mở `http://<ip>:5678/` là đủ.
Gọi API trực tiếp thì đính header `X-Reader-Token`. Không có token đúng thì mọi
đường, kể cả trang chủ, trả 401. Chạy không token trên `0.0.0.0` vẫn được nhưng
log sẽ cảnh báo một dòng — chỉ nên thế khi đã có lớp chặn khác (VPN, tường lửa).

### Lệnh chạy đầy đủ

Gom hết lại một chỗ. Viết thành một file cho khỏi gõ lại mỗi lần, ví dụ
`chay.sh` ngay trong thư mục dự án (`.gitignore` đã bỏ qua `*.log`, còn
`chay.sh` thì tự thêm nếu nó chứa mật khẩu):

```bash
#!/bin/bash
cd "$(dirname "$0")"

export READER_TOKEN=mekong          # bỏ dòng này là trang mở cho mọi người
export READER_BROWSER_CHANNEL=             # để rỗng: dùng Chromium của Playwright
export READER_PROXY=http://user:pass@host:port    # proxy dân cư, bỏ nếu không có

# Gửi mã về hộp thư của bạn - bỏ cả khối nếu không cần
export READER_SMTP_HOST=smtp.gmail.com
export READER_SMTP_USER=toi@gmail.com
export READER_SMTP_PASSWORD=<mật khẩu ứng dụng 16 ký tự>
export READER_MAIL_TO=toi@gmail.com

# Bắn mã về hệ thống của bạn - bỏ nếu không cần
export READER_WEBHOOK=https://cho-cua-ban/hook
export READER_WEBHOOK_SECRET=chuoi-bi-mat

# "$@": để `./chay.sh --check` hay `./chay.sh --port 8080` truyền được xuống
exec uv run python -m reader --host 0.0.0.0 "$@"
```

```bash
chmod +x chay.sh
nohup ./chay.sh > reader.log 2>&1 &     # chạy nền, log vào reader.log
tail -f reader.log                      # dòng đầu có sẵn địa chỉ kèm token
```

Mấy việc hay phải làm:

```bash
pkill -f "python -m reader"      # dừng
./chay.sh --check                # thử mở trình duyệt, in lỗi thật nếu hỏng
curl -s localhost:5678/api/jobs -H "X-Reader-Token: $READER_TOKEN"   # xem các lượt
```

**Khởi động lại là mất hết các lượt đang chạy** (chúng chỉ sống trong bộ nhớ),
kể cả mã đã lấy được. Mã nào cần giữ thì để `webhook` hoặc mail mang đi ngay
lúc có, đừng dựa vào tab đang mở.

Muốn nó tự chạy lại sau khi reboot thì dựng một unit systemd
(`/etc/systemd/system/reader.service`, nhớ `chmod 600` vì nó chứa mật khẩu):

```ini
[Unit]
Description=reader - lấy mã OTP từ Outlook
After=network-online.target

[Service]
WorkingDirectory=/duong/dan/reader
ExecStart=/duong/dan/reader/chay.sh
Restart=on-failure
User=<tên người dùng>

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now reader
journalctl -u reader -f
```

Lượt lấy mã **kẹt ở `đang mở trình duyệt`** nghĩa là kẹt ở đúng bước khởi động
Chromium, và lỗi thật nằm trong log của luồng nền. Chạy riêng bước đó ra để nó
hiện thẳng:

```bash
uv run python -m reader --check
```

Hai thứ hay thiếu nhất trên server: **Google Chrome** (mặc định
`READER_BROWSER_CHANNEL=chrome` đòi Chrome thật — server thì đặt rỗng để dùng
Chromium của Playwright) và **thư viện hệ thống** cho Chromium (cài bằng
`playwright install --with-deps chromium`). `--check` nhận ra cả hai và nói
thẳng phải làm gì.

Log đi ra stdout/stderr của tiến trình, nên nhớ hứng lại lúc khởi động:

```bash
nohup uv run python -m reader --host 0.0.0.0 --token chuoi-cua-ban \
      > reader.log 2>&1 &
tail -f reader.log                 # systemd thì: journalctl -u <unit> -f
```

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
READER_PROXY=http://user:pass@host:port uv run python -m reader --host 0.0.0.0 --token ...
uv run python -m reader --check        # in ra "qua proxy ..." để chắc là nó có hiệu lực
```

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

# trong chay.sh của reader:
export READER_PROXY=http://reader:<TOKEN>@127.0.0.1:3128
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

Mọi thứ có mặc định dùng được ngay; đổi bằng biến môi trường:

| Biến | Mặc định | Nghĩa |
|---|---|---|
| `READER_TOKEN` | rỗng | khoá truy cập; rỗng là ai mở được trang cũng dùng được |
| `READER_HOST` | `127.0.0.1` | `0.0.0.0` để máy khác gọi được |
| `READER_PORT` | `5678` | cổng của giao diện |
| `READER_HEADLESS` | theo máy | mặc định `true` khi máy không có màn hình; `true` thì gặp 2FA bạn không còn chỗ nào để xử lý |
| `READER_PROFILES` | `.profiles` | nơi giữ phiên Outlook, mỗi email một thư mục con |
| `READER_INBOX_URL` | `https://outlook.live.com/mail/0/` | hộp thư cần mở |
| `READER_BROWSER_CHANNEL` | `chrome` | rỗng thì dùng Chromium của Playwright |
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

## API

### Một lần gọi, nhận thẳng mã

Cho hệ thống khác gọi sang: `POST /api/code` chạy cả lượt rồi mới trả lời.

```bash
curl -X POST http://<ip>:5678/api/code \
     -H 'content-type: application/json' \
     -H 'X-Reader-Token: <token>' \
     -d '{"account": "ten@outlook.com|MatKhau123"}'
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
| 400 | chuỗi tài khoản không đọc được |
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
# mặc định cho mọi lượt, khai lúc chạy server
READER_WEBHOOK=https://cho-cua-ban/hook \
READER_WEBHOOK_SECRET=chuoi-bi-mat \
uv run python -m reader --host 0.0.0.0

# hoặc riêng cho một lần gọi (cái này thắng cái trên)
curl -X POST http://<ip>:5678/api/code -H 'content-type: application/json' \
     -d '{"account": "ten@outlook.com|MatKhau123", "webhook": "https://cho-khac/hook"}'
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
READER_SMTP_HOST=smtp.gmail.com \
READER_SMTP_PORT=587 \
READER_SMTP_USER=toi@gmail.com \
READER_SMTP_PASSWORD=<mật khẩu ứng dụng, không phải mật khẩu Gmail> \
READER_MAIL_TO=toi@gmail.com \
uv run python -m reader --host 0.0.0.0
```

Thư nhận được có **mã ngay trên tiêu đề** — `483921 - mã OTP của ten@outlook.com`
— vì trên điện thoại thông báo đẩy chỉ hiện tiêu đề, để mã ở đấy là đọc được mà
không phải mở thư. Thân thư có thêm hộp thư nguồn và dòng chủ đề của mail chứa
mã.

Từng lần gọi muốn gửi về một địa chỉ khác thì truyền thêm `mail_to`:

```bash
curl -X POST http://<ip>:5678/api/code -H 'content-type: application/json' \
     -d '{"account": "ten@outlook.com|MatKhau123", "mail_to": "rieng@vi-du.com"}'
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
| `POST /api/otp` `{"account": "mail\|pass", "sign_out_after": false}` | tạo một lượt, trả về `id` |
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
| `reader/account.py` | tách chuỗi dán vào thành email + mật khẩu |
| `reader/proxy.py` | đọc chuỗi proxy cho trình duyệt |
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
(trong iframe) → "Stay signed in?" → hộp thư → mã — nên nó mất khoảng hai phút.

## Điểm yếu đã biết

1. **Phụ thuộc DOM Outlook.** Microsoft đổi layout là phần quét mù, và biểu hiện
   ra ngoài chỉ là "hết giờ mà không thấy mã" chứ không phải một lỗi rõ ràng.
2. **Không xác minh người gửi.** Mã lấy được là mã trong mail mới nhất trông
   giống mail OTP, bất kể ai gửi.
3. **Quét có ghi, không chỉ đọc.** Mã không nằm ở dòng xem trước thì agent mở
   mail ra, tức là **đánh dấu đã đọc**.
4. **"Gần nhất" là gần nhất trong hộp thư, không phải "mới tới".** Nếu bạn cần mã
   vừa được gửi, hãy bấm Lấy mã **sau** khi dịch vụ kia gửi mail.
