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
| `READER_POLL_SECONDS` | `5` | nhịp đọc lại danh sách mail |
| `READER_REFRESH_SECONDS` | `120` | nhịp tải lại trang (chỉ là lưới an toàn) |
| `READER_TIMEOUT_SECONDS` | `180` | hạn cho cả một lượt lấy mã |

## API

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
