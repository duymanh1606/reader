#!/usr/bin/env bash
# Dựng reader để chạy trên server: cài phụ thuộc, sinh chay.sh, rồi kiểm.
#
#   ./setup.sh                                  # hỏi từng giá trị
#   READER_TOKEN=... READER_PROXY=... ./setup.sh --yes   # không hỏi gì
#   ./setup.sh --check                          # chỉ kiểm cái đang có
#
# Chạy lại được nhiều lần: nó KHÔNG ghi đè chay.sh đã có (file đó mang token,
# ghi đè là mất token). Muốn làm lại thì xoá chay.sh rồi chạy lại.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 2

MODE="run"; ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        --check) MODE="check" ;;
        --yes|-y) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "tham số lạ: $arg" >&2; exit 2 ;;
    esac
done

warn=0
ok()   { printf '  OK    %s\n' "$*"; }
bad()  { printf '  LỖI   %s\n' "$*"; warn=$((warn+1)); }
note() { printf '  .     %s\n' "$*"; }
head1(){ printf '\n== %s\n' "$*"; }
die()  { printf '\nDỪNG: %s\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------- 1. phụ thuộc
head1 "Phụ thuộc"

command -v uv >/dev/null || die "chưa có uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
ok "uv: $(uv --version 2>/dev/null)"

if [ "$MODE" != "check" ]; then
    uv sync --quiet || die "uv sync thất bại"
    ok "uv sync xong"
    # --with-deps bắt buộc trên server trắng: Chromium cần hàng chục thư viện hệ
    # thống (libnss3, libatk...) mà image server tối giản không có, và lỗi thiếu
    # chúng hiện ra lúc LAUNCH chứ không lúc install.
    uv run playwright install --with-deps chromium >/dev/null 2>&1 \
        && ok "Chromium đã cài" \
        || bad "playwright install thất bại — chạy tay để xem lỗi: uv run playwright install --with-deps chromium"
fi

# ------------------------------------------------------- 2. sandbox Chromium
head1 "Sandbox Chromium"

# reader cố ý lùi về chạy không sandbox nếu không dựng được (xem
# reader/browser.py), nhưng đây là máy mở trang web thật bằng profile có phiên
# đăng nhập thật — sandbox là hàng rào chính của trình duyệt. Nguyên nhân gần
# như luôn là user namespace bị khoá.
userns_ok=1
if [ -r /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]; then
    [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)" = "0" ] || userns_ok=0
    KNOB="kernel.apparmor_restrict_unprivileged_userns = 0"
elif [ -r /proc/sys/kernel/unprivileged_userns_clone ]; then
    [ "$(cat /proc/sys/kernel/unprivileged_userns_clone)" = "1" ] || userns_ok=0
    KNOB="kernel.unprivileged_userns_clone = 1"
else
    KNOB=""
fi

if [ -z "$KNOB" ]; then
    note "kernel không có knob userns nào để kiểm — bỏ qua"
elif [ "$userns_ok" = 1 ]; then
    ok "user namespace mở, sandbox dựng được"
else
    bad "user namespace bị khoá — Chromium sẽ chạy KHÔNG sandbox"
    note "    sudo sh -c 'echo \"$KNOB\" > /etc/sysctl.d/60-chromium-sandbox.conf' && sudo sysctl --system"
fi

# ------------------------------------------------------------- 3. chay.sh
head1 "chay.sh"

if [ -f chay.sh ]; then
    ok "đã có — không ghi đè (nó mang token)"
    grep -q '^export READER_PROXY=.*<' chay.sh && \
        bad "READER_PROXY còn chứa dấu '<' — placeholder chưa thay bằng token thật"
    grep -qE '^export READER_TOKEN=\s*$' chay.sh && \
        bad "READER_TOKEN RỖNG — giao diện mở cho mọi người, mà nó nhận mật khẩu hộp thư"
elif [ "$MODE" = "check" ]; then
    bad "chưa có chay.sh"
else
    TOKEN="${READER_TOKEN:-}"
    PROXY="${READER_PROXY:-}"
    HOSTBIND="${READER_HOST:-0.0.0.0}"

    if [ "$ASSUME_YES" = 0 ]; then
        echo "  Token mở giao diện web. Bỏ trống = tự sinh ngẫu nhiên."
        echo "  Chỉ dùng chữ, số, '-' và '_' — nó đi trong query string."
        [ -z "$TOKEN" ] && read -rp "  READER_TOKEN: " TOKEN
        echo
        echo "  Proxy cho trình duyệt, dạng http://<workspace>:<token>@<ip>:3128"
        echo "  Bỏ trống = không qua proxy."
        [ -z "$PROXY" ] && read -rp "  READER_PROXY: " PROXY
    fi
    [ -z "$TOKEN" ] && { TOKEN="$(openssl rand -hex 16)"; note "READER_TOKEN tự sinh"; }

    case "$TOKEN" in
        *[^A-Za-z0-9_-]*) die "READER_TOKEN có ký tự ngoài [A-Za-z0-9_-]; nó đi trong URL nên sẽ bị hiểu sai" ;;
    esac
    case "$PROXY" in
        *'<'*|*'>'*) die "READER_PROXY còn dấu '<' hoặc '>' — dán token thật, không dán placeholder" ;;
    esac

    # Heredoc có ngoặc kép quanh EOF cho phần cần nguyên văn; các biến được chèn
    # bằng printf để không phải escape $0/$@ của bash trong file sinh ra.
    {
        printf '#!/bin/bash\n'
        printf '# Sinh bởi ./setup.sh — file này MANG TOKEN, đã nằm trong .gitignore.\n'
        printf 'cd "$(dirname "$0")"\n\n'
        printf 'export READER_TOKEN=%s\n' "$TOKEN"
        printf 'export READER_BROWSER_CHANNEL=\n'
        [ -n "$PROXY" ] && printf 'export READER_PROXY=%s\n' "$PROXY"
        printf '\nexec uv run python -m reader --host %s "$@"\n' "$HOSTBIND"
    } > chay.sh
    chmod 700 chay.sh
    ok "đã sinh, mode 700"
fi

grep -qxF 'chay.sh' .gitignore 2>/dev/null \
    && ok ".gitignore đã chặn chay.sh" \
    || { echo 'chay.sh' >> .gitignore; ok "đã thêm chay.sh vào .gitignore"; }

# -------------------------------------------------------- 4. kiểm đường proxy
head1 "Đường ra Internet"

PROXY_URL=$(grep -oP '^export READER_PROXY=\K.*' chay.sh 2>/dev/null)

if [ -z "$PROXY_URL" ]; then
    note "không cấu hình proxy — trình duyệt đi bằng IP của chính máy này"
else
    # Che token khi in. Cùng quy ước với reader/proxy.py: log không bao giờ
    # chứa mật khẩu proxy.
    safe=$(printf '%s' "$PROXY_URL" | sed -E 's|://([^:]+):[^@]*@|://\1:***@|')
    note "proxy: $safe"

    # curl trước Chromium: nó tách được "đường mạng/token sai" khỏi "trình duyệt
    # sai". Phải đọc %{http_connect}, KHÔNG %{http_code} — CONNECT bị từ chối
    # thì không có response HTTP nào nên http_code là 000.
    body=$(curl -s --max-time 20 -x "$PROXY_URL" https://api.ipify.org 2>/dev/null)
    code=$(curl -s -o /dev/null --max-time 20 -w '%{http_connect}' \
             -x "$PROXY_URL" https://api.ipify.org 2>/dev/null)
    if [ -n "$body" ]; then
        ok "ra Internet bằng IP: $body"
    else
        case "$code" in
            407) bad "407 — token sai, hoặc đã revoke, hoặc workspace id trong URL không đúng" ;;
            403) bad "403 — chưa có mapping workspace->route bên egw, hoặc đích bị chặn" ;;
            503) bad "503 — route UNHEALTHY bên egw, hoặc vượt giới hạn kết nối" ;;
            000|"") bad "không có phản hồi nào — IP máy này ngoài allowed_client_cidrs (egw đóng kết nối không trả lời), hoặc không tới được proxy" ;;
            *)   bad "proxy trả $code" ;;
        esac
    fi
fi

if [ "$MODE" != "check" ] && [ -f chay.sh ]; then
    head1 "Thử mở trình duyệt"
    ./chay.sh --check 2>&1 | sed 's/^/  /'
fi

# ------------------------------------------------------------- 5. tóm tắt
head1 "Kết quả"
if [ "$warn" -eq 0 ]; then
    cat <<'NEXT'
  Không có vấn đề nào.

Chạy thật:
  nohup ./chay.sh > reader.log 2>&1 &
  head -3 reader.log        # dòng đầu có sẵn địa chỉ kèm token

Rồi kiểm lớp cuối TRÊN MÁY EGW — đây là bằng chứng duy nhất cho việc trình
duyệt thật sự đi qua proxy:
  docker exec egw-pg psql -U egw -d egw -c \
    "select ts, route_id, status, target_host from conn_logs \
     where workspace_id='reader' order by ts desc limit 10"
NEXT
    exit 0
fi
echo "  $warn vấn đề ở trên."
exit 1
