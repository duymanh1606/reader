#!/usr/bin/env bash
# MỘT lệnh: cài những gì còn thiếu, chạy reader trên máy này, mở ra Internet qua ngrok.
#
#   ./run-ngrok.sh             lần đầu: cài hết rồi chạy; các lần sau: chỉ chạy
#   ./run-ngrok.sh --no-run    chỉ cài/kiểm, không chạy
#   Ctrl+C                     tắt cả reader lẫn ngrok
#
# Tự cài khi thiếu: uv, thư viện Python, Chromium (khi máy không có Chrome thật),
# .env (token ngẫu nhiên, mode 600), ngrok (bản Linux, vào ~/.local/bin).
# Hỏi đúng một thứ, và chỉ một lần: authtoken ngrok - hoặc truyền sẵn:
#   NGROK_AUTHTOKEN=... ./run-ngrok.sh
# Muốn đi qua proxy ngay từ lần đầu: READER_PROXY=http://... ./run-ngrok.sh
#
# reader chỉ nghe 127.0.0.1: đường duy nhất từ ngoài vào là ngrok, và mọi
# request vẫn phải có READER_TOKEN. Trong WSL dùng được cả ngrok.exe của Windows
# - Windows gọi localhost:PORT là tới WSL.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 2
RUN=1
for arg in "$@"; do
    case "$arg" in
        --no-run) RUN=0 ;;
        -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
        *) echo "tham số lạ: $arg" >&2; exit 2 ;;
    esac
done

ok()  { printf '  OK    %s\n' "$*"; }
die() { printf '\nDỪNG: %s\n' "$*" >&2; exit 1; }
export PATH="$HOME/.local/bin:$PATH"

# ---------------------------------------------------------------- 1. uv
if ! command -v uv >/dev/null; then
    echo "  ..    chưa có uv - đang cài (https://astral.sh/uv)"
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 \
        || die "cài uv không được - cài tay: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi
ok "uv $(uv --version 2>/dev/null | awk '{print $2}')"

# ------------------------------------------------- 2. thư viện + trình duyệt
uv sync --quiet || die "uv sync thất bại"
ok "thư viện Python"

CHROME=$(command -v google-chrome || command -v google-chrome-stable || true)
if [ -z "$CHROME" ]; then
    # Không có Chrome thật thì dùng Chromium của Playwright. Lỗi thiếu thư viện
    # hệ thống chỉ hiện lúc mở trình duyệt, nên cài kèm --with-deps khi có sudo.
    if ! ls "$HOME"/.cache/ms-playwright/chromium-* >/dev/null 2>&1; then
        echo "  ..    chưa có trình duyệt - đang cài Chromium (vài phút)"
        if sudo -n true 2>/dev/null; then
            uv run playwright install --with-deps chromium >/dev/null 2>&1
        else
            uv run playwright install chromium >/dev/null 2>&1
        fi || die "cài Chromium không được: uv run playwright install --with-deps chromium"
    fi
    ok "trình duyệt: Chromium của Playwright"
else
    ok "trình duyệt: Chrome thật ($CHROME)"
fi

# ---------------------------------------------------------------- 3. .env
if [ ! -f .env ]; then
    channel=""; [ -n "$CHROME" ] && channel="chrome"
    proxy_line="# READER_PROXY=http://192.168.208.1:60000   # bỏ # để đi qua proxy (app 9proxy...)"
    [ -n "${READER_PROXY:-}" ] && proxy_line="READER_PROXY=$READER_PROXY"
    (
        umask 077
        cat > .env <<EOF
# Sinh bởi ./run-ngrok.sh - file này MANG TOKEN, mode 600, đã nằm trong .gitignore.
# Sửa xong: Ctrl+C rồi chạy lại ./run-ngrok.sh

# Chỉ nghe trên máy này - đường duy nhất từ ngoài vào là ngrok.
READER_HOST=127.0.0.1
READER_PORT=5678
# Địa chỉ ngrok là công khai: token là thứ duy nhất chặn người lạ.
READER_TOKEN=$(openssl rand -hex 16)

# Rỗng = Chromium của Playwright; "chrome" = Chrome thật (Microsoft ít nghi hơn).
READER_BROWSER_CHANNEL=$channel
# Hiện cửa sổ: gặp 2FA/CAPTCHA thì xử lý ngay trên máy.
READER_HEADLESS=false

$proxy_line
EOF
    )
    ok "đã tạo .env (token ngẫu nhiên, mode 600)"
else
    ok ".env đã có - giữ nguyên"
fi

envval() { sed -nE "s/^$1=//p" .env | tail -1; }
PORT=$(envval READER_PORT); PORT=${PORT:-5678}
TOKEN=$(envval READER_TOKEN)
[ -n "$TOKEN" ] || die "READER_TOKEN trong .env rỗng - mở ra Internet mà không token là ai cũng dán được tài khoản"
case "$(envval READER_HOST)" in
    127.0.0.1|localhost|"") ;;
    *) echo "  !     READER_HOST không phải 127.0.0.1 - reader mở cả ra mạng ngoài, không chỉ qua ngrok" ;;
esac

# -------------------------------------------------------------- 4. ngrok
NGROK=$(command -v ngrok || command -v ngrok.exe || true)
if [ -z "$NGROK" ]; then
    case "$(uname -m)" in
        x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) arch="" ;;
    esac
    [ -n "$arch" ] || die "không cài tự động được ngrok cho máy $(uname -m) - tải ở https://ngrok.com/download"
    echo "  ..    chưa có ngrok - đang cài vào ~/.local/bin"
    mkdir -p "$HOME/.local/bin"
    curl -sSL "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-$arch.tgz" \
        | tar -xz -C "$HOME/.local/bin" ngrok \
        || die "tải ngrok không được - tải tay ở https://ngrok.com/download"
    NGROK="$HOME/.local/bin/ngrok"
fi
ok "ngrok: $NGROK"

add_token() {
    "$NGROK" config add-authtoken "$1" >/dev/null 2>&1 || die "ngrok không nhận authtoken này"
    ok "đã lưu authtoken ngrok"
}
[ -n "${NGROK_AUTHTOKEN:-}" ] && add_token "$NGROK_AUTHTOKEN"

if [ "$RUN" = 0 ]; then
    echo; echo "Cài xong. Chạy: ./run-ngrok.sh"
    exit 0
fi

# ------------------------------------------------------------ 5. chạy
pids=()
NLOG=$(mktemp)
cleanup() { [ ${#pids[@]} -gt 0 ] && kill "${pids[@]}" 2>/dev/null; rm -f "$NLOG"; exit "${1:-0}"; }
trap cleanup INT TERM

if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then
    echo "  .     reader đã chạy sẵn ở cổng $PORT - dùng luôn (sửa .env thì tắt nó trước: pkill -f 'python -m reader')"
else
    uv run python -m reader >> reader-local.log 2>&1 &
    pids+=($!)
    for _ in $(seq 1 30); do
        curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break
        sleep 1
    done
    curl -s -o /dev/null "http://127.0.0.1:$PORT/" \
        || { echo "reader không lên - xem: tail reader-local.log" >&2; cleanup 1; }
    ok "reader đang chạy, log ở reader-local.log"
fi

# Mở đường hầm; chờ tới khi có địa chỉ hoặc có lỗi. Trả 0 nếu có URL.
start_ngrok() {
    : > "$NLOG"
    "$NGROK" http "$PORT" --log stdout --log-format json > "$NLOG" 2>&1 &
    NPID=$!
    for _ in $(seq 1 30); do
        URL=$(grep -oE '"url":"https://[^"]+"' "$NLOG" | head -1 | cut -d'"' -f4)
        [ -n "$URL" ] && return 0
        grep -q 'ERR_NGROK_' "$NLOG" && break
        kill -0 "$NPID" 2>/dev/null || break
        sleep 1
    done
    kill "$NPID" 2>/dev/null
    return 1
}

URL=""
if ! start_ngrok; then
    if grep -qE 'ERR_NGROK_(4018|105)' "$NLOG" && [ -t 0 ]; then
        # Chưa gắn tài khoản (hoặc token sai): hỏi một lần, lưu lại, thử lại.
        echo
        echo "ngrok cần authtoken của tài khoản (miễn phí):"
        echo "  https://dashboard.ngrok.com/get-started/your-authtoken"
        read -rsp "Dán authtoken: " tok; echo
        [ -n "$tok" ] || cleanup 1
        add_token "$tok"
        start_ngrok || true
    fi
fi
if [ -z "$URL" ]; then
    if grep -q ERR_NGROK_334 "$NLOG"; then
        # Gói miễn phí: một địa chỉ chỉ mở được ở MỘT ngrok cùng lúc.
        echo "ngrok khác đang giữ địa chỉ này. Tắt nó rồi chạy lại:" >&2
        echo "  pkill -f 'ngrok http'; taskkill.exe /IM ngrok.exe /F 2>/dev/null" >&2
        echo "  (hoặc https://dashboard.ngrok.com/agents -> Stop)" >&2
    elif grep -qE 'ERR_NGROK_(4018|105)' "$NLOG"; then
        echo "ngrok chưa có authtoken hợp lệ - chạy: NGROK_AUTHTOKEN=<token> ./run-ngrok.sh" >&2
    else
        echo "ngrok không mở được đường hầm:" >&2
        grep -oE '"err":"[^"]{4,}' "$NLOG" | grep -v 'u003cnil' | head -3 >&2
    fi
    cleanup 1
fi
pids+=("$NPID")
ok "ngrok đang chạy"

cat <<EOF

Mở từ bất kỳ đâu (lần đầu kèm token, sau đó token nằm trong cookie):
  $URL/?token=$TOKEN

Gọi API: thêm header  X-Reader-Token: $TOKEN
          và          ngrok-skip-browser-warning: 1   (bỏ trang cảnh báo của ngrok)

Để cửa sổ này mở. Ctrl+C để tắt.
EOF
wait
