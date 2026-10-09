#!/usr/bin/env bash
# Dựng reader trên server: cài phụ thuộc, sinh .env, kiểm, chạy bằng systemd.
#
#   ./setup.sh             cài + tạo .env (hỏi token/proxy) + kiểm + thử trình duyệt
#   ./setup.sh --service   như trên, rồi cài/khởi động lại unit systemd `reader`
#   ./setup.sh --update    git pull, cài lại phụ thuộc, khởi động lại service
#   ./setup.sh --check     chỉ kiểm cái đang có, không sửa gì
#   READER_TOKEN=... READER_PROXY=... ./setup.sh --yes --service   # không hỏi gì
#
# Chạy lại được nhiều lần: .env đã có thì KHÔNG bị ghi đè (nó mang token).
# Có chay.sh của bản cũ mà chưa có .env thì các biến trong đó được chuyển sang.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 2
DIR="$(pwd)"
ENV=.env
UNIT=/etc/systemd/system/reader.service

MODE="install"; ASSUME_YES=0; SERVICE=0
for arg in "$@"; do
    case "$arg" in
        --check)   MODE="check" ;;
        --update)  MODE="update"; SERVICE=1 ;;
        --service) SERVICE=1 ;;
        --yes|-y)  ASSUME_YES=1 ;;
        -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
        *) echo "tham số lạ: $arg" >&2; exit 2 ;;
    esac
done

warn=0
ok()   { printf '  OK    %s\n' "$*"; }
bad()  { printf '  LỖI   %s\n' "$*"; warn=$((warn+1)); }
note() { printf '  .     %s\n' "$*"; }
head1(){ printf '\n== %s\n' "$*"; }
die()  { printf '\nDỪNG: %s\n' "$*" >&2; exit 1; }

# Giá trị của một biến trong .env, bỏ ngoặc kép/đơn - cùng luật với
# reader/config.py:load_env_file.
envval() {
    [ -f "$ENV" ] || return 0
    sed -nE "s/^(export )?$1=//p" "$ENV" | tail -1 \
        | sed -E -e "s/^[[:space:]]*([\"'])(.*)\1[[:space:]]*\$/\2/;t" \
                 -e 's/^[[:space:]]*#.*//' -e 's/[[:space:]]+#.*//' -e 's/^[[:space:]]+//'
}

as_root() { if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi; }

# ------------------------------------------------------------ 0. cập nhật
if [ "$MODE" = "update" ]; then
    head1 "Cập nhật mã nguồn"
    git pull --ff-only || die "git pull không fast-forward được - xem 'git status'"
    ok "đã kéo về: $(git log -1 --format='%h %s')"
fi

# ------------------------------------------------------------- 1. phụ thuộc
head1 "Phụ thuộc"

command -v uv >/dev/null || die "chưa có uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
ok "uv: $(uv --version 2>/dev/null)"

if [ "$MODE" != "check" ]; then
    uv sync --quiet || die "uv sync thất bại"
    ok "uv sync xong"
    # --with-deps bắt buộc trên server trắng: Chromium cần hàng chục thư viện hệ
    # thống (libnss3, libatk...) mà image server tối giản không có, và lỗi thiếu
    # chúng hiện ra lúc LAUNCH chứ không lúc install. --with-deps gọi apt qua
    # sudo, mà output bị giấu - nên xin sudo TRƯỚC, công khai, để nó không ngồi
    # chờ một mật khẩu không ai thấy lời hỏi. Không có sudo thì cài riêng Chromium.
    deps=""
    if [ "$(id -u)" = 0 ] || sudo -n true 2>/dev/null \
        || { [ "$ASSUME_YES" = 0 ] && [ -t 0 ] && sudo -v; }; then
        deps="--with-deps"
    fi
    if [ -n "$deps" ] && uv run playwright install --with-deps chromium </dev/null >/dev/null 2>&1; then
        ok "Chromium và thư viện hệ thống đã cài"
    elif uv run playwright install chromium >/dev/null 2>&1; then
        ok "Chromium đã cài"
        note "chưa cài được thư viện hệ thống (cần sudo) - nếu --check báo thiếu thư viện:"
        note "    sudo .venv/bin/playwright install-deps chromium"
    else
        bad "playwright install thất bại - chạy tay để xem lỗi: uv run playwright install --with-deps chromium"
    fi
fi

# ------------------------------------------------------- 2. sandbox Chromium
head1 "Sandbox Chromium"

# reader cố ý lùi về chạy không sandbox nếu không dựng được (xem
# reader/browser.py), nhưng đây là máy mở trang web thật bằng profile có phiên
# đăng nhập thật - sandbox là hàng rào chính của trình duyệt. Nguyên nhân gần
# như luôn là user namespace bị khoá.
KNOB=""; userns_ok=1
if [ -r /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]; then
    KNOB="kernel.apparmor_restrict_unprivileged_userns = 0"
    [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)" = "0" ] || userns_ok=0
elif [ -r /proc/sys/kernel/unprivileged_userns_clone ]; then
    KNOB="kernel.unprivileged_userns_clone = 1"
    [ "$(cat /proc/sys/kernel/unprivileged_userns_clone)" = "1" ] || userns_ok=0
fi

if [ -z "$KNOB" ]; then
    note "kernel không có knob userns nào để kiểm - bỏ qua"
elif [ "$userns_ok" = 1 ]; then
    ok "user namespace mở, sandbox dựng được"
else
    bad "user namespace bị khoá - Chromium sẽ chạy KHÔNG sandbox"
    note "    sudo sh -c 'echo \"$KNOB\" > /etc/sysctl.d/60-chromium-sandbox.conf' && sudo sysctl --system"
fi

# ----------------------------------------------------------------- 3. .env
head1 ".env"

write_env() {
    local token="$1" proxy="$2" host="$3"
    # umask trong subshell: file sinh ra mode 600 ngay từ đầu, không có khoảnh
    # khắc nào người khác trên máy đọc được token.
    (
        umask 077
        cat > "$ENV" <<EOF
# Sinh bởi ./setup.sh - file này MANG TOKEN, mode 600, đã nằm trong .gitignore.
# Đủ danh sách biến: .env.example. Sửa xong: sudo systemctl restart reader

READER_HOST=$host
READER_TOKEN=$token
# Rỗng: dùng Chromium của Playwright (server thường không có Google Chrome).
READER_BROWSER_CHANNEL=
EOF
        if [ -n "$proxy" ]; then
            printf 'READER_PROXY=%s\n' "$proxy" >> "$ENV"
        else
            printf '# READER_PROXY=http://user:pass@host:3128\n' >> "$ENV"
        fi
        cat >> "$ENV" <<'EOF'

# Gửi mã về hộp thư của bạn - bỏ dấu # để bật
# READER_SMTP_HOST=smtp.gmail.com
# READER_SMTP_USER=toi@gmail.com
# READER_SMTP_PASSWORD=mat-khau-ung-dung-16-ky-tu
# READER_MAIL_TO=toi@gmail.com

# Bắn mã về hệ thống của bạn - bỏ dấu # để bật
# READER_WEBHOOK=https://cho-cua-ban/hook
# READER_WEBHOOK_SECRET=chuoi-bi-mat
EOF
    )
}

if [ -f "$ENV" ]; then
    ok "đã có - không ghi đè (nó mang token)"
elif [ "$MODE" = "check" ]; then
    bad "chưa có .env - chạy ./setup.sh để tạo"
elif [ -f chay.sh ]; then
    # Bản cũ để biến dưới dạng `export READER_X=...` trong chay.sh, còn host
    # nằm ở `--host` của dòng exec.
    (
        umask 077
        echo "# Chuyển từ chay.sh bởi ./setup.sh - file này MANG TOKEN, mode 600."
        sed -nE 's/^export (READER_[A-Z_]+=.*)$/\1/p' chay.sh
        host=$(grep -oE -- '--host +[^ ]+' chay.sh | awk '{print $2}' | tail -1)
        grep -qE '^export READER_HOST=' chay.sh || echo "READER_HOST=${host:-0.0.0.0}"
    ) > "$ENV"
    ok "đã chuyển các biến từ chay.sh sang .env"
    note "chay.sh không còn dùng nữa - kiểm .env rồi xoá: rm chay.sh"
else
    TOKEN="${READER_TOKEN:-}"
    PROXY="${READER_PROXY:-}"
    if [ "$ASSUME_YES" = 0 ]; then
        echo "  Token mở giao diện web. Bỏ trống = tự sinh ngẫu nhiên."
        echo "  Chỉ dùng chữ, số, '-' và '_' - nó đi trong query string."
        [ -z "$TOKEN" ] && read -rp "  READER_TOKEN: " TOKEN
        echo
        echo "  Proxy cho trình duyệt, dạng http://user:pass@host:3128"
        echo "  Bỏ trống = không qua proxy."
        [ -z "$PROXY" ] && read -rp "  READER_PROXY: " PROXY
    fi
    [ -z "$TOKEN" ] && { TOKEN="$(openssl rand -hex 16)"; note "READER_TOKEN tự sinh"; }

    case "$TOKEN" in
        *[^A-Za-z0-9_-]*) die "READER_TOKEN có ký tự ngoài [A-Za-z0-9_-]; nó đi trong URL nên sẽ bị hiểu sai" ;;
    esac
    case "$PROXY" in
        *'<'*|*'>'*) die "READER_PROXY còn dấu '<' hoặc '>' - dán token thật, không dán placeholder" ;;
    esac

    write_env "$TOKEN" "$PROXY" "${READER_HOST:-0.0.0.0}"
    ok "đã sinh, mode 600"
fi

if [ -f "$ENV" ]; then
    if [ "$(stat -c %a "$ENV")" != 600 ] && [ "$MODE" != "check" ]; then
        chmod 600 "$ENV" && ok "đã chmod 600"
    fi
    [ "$(stat -c %a "$ENV")" = 600 ] || bad ".env đọc được bởi người khác - chmod 600 .env"
    [ -n "$(envval READER_TOKEN)" ] || \
        bad "READER_TOKEN RỖNG - giao diện mở cho mọi người, mà nó nhận mật khẩu hộp thư"
    case "$(envval READER_PROXY)" in
        *'<'*) bad "READER_PROXY còn chứa dấu '<' - placeholder chưa thay bằng token thật" ;;
    esac
fi

# -------------------------------------------------------- 4. kiểm đường proxy
head1 "Đường ra Internet"

PROXY_URL=$(envval READER_PROXY)
if [ -z "$PROXY_URL" ]; then
    note "không cấu hình proxy - trình duyệt đi bằng IP của chính máy này"
else
    # Che mật khẩu khi in. Cùng quy ước với reader/proxy.py.
    note "proxy: $(printf '%s' "$PROXY_URL" | sed -E 's|://([^:]+):[^@]*@|://\1:***@|')"

    # curl trước Chromium: nó tách được "đường mạng/token sai" khỏi "trình duyệt
    # sai". Phải đọc %{http_connect}, KHÔNG %{http_code} - CONNECT bị từ chối
    # thì không có response HTTP nào nên http_code là 000.
    body=$(curl -s --max-time 20 -x "$PROXY_URL" https://api.ipify.org 2>/dev/null)
    if [ -n "$body" ]; then
        ok "ra Internet bằng IP: $body"
    else
        code=$(curl -s -o /dev/null --max-time 20 -w '%{http_connect}' \
                 -x "$PROXY_URL" https://api.ipify.org 2>/dev/null)
        case "$code" in
            407) bad "407 - sai user/mật khẩu proxy (với egw: token sai, đã revoke, hoặc sai workspace id)" ;;
            403) bad "403 - proxy từ chối đích (với egw: chưa có mapping workspace->route)" ;;
            503) bad "503 - proxy không có đường ra (với egw: route UNHEALTHY hoặc vượt giới hạn)" ;;
            000|"") bad "không có phản hồi - không tới được proxy, hoặc IP máy này không được phép (egw: allowed_client_cidrs)" ;;
            *)   bad "proxy trả $code" ;;
        esac
    fi
fi

# ------------------------------------------------------ 5. thử mở trình duyệt
if [ "$MODE" != "check" ] && [ -f "$ENV" ]; then
    head1 "Thử mở trình duyệt"
    # `--check` tự đọc .env (reader/config.py), đúng như service sẽ chạy.
    uv run python -m reader --check 2>&1 | sed 's/^/  /'
    [ "${PIPESTATUS[0]}" = 0 ] || bad "trình duyệt không mở được - xem lỗi ngay trên"
fi

# --------------------------------------------------------------- 6. systemd
install_service() {
    command -v systemctl >/dev/null || { bad "máy này không có systemd"; return; }
    local unit
    unit=$(cat <<EOF
[Unit]
Description=reader - lấy mã OTP từ Outlook
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$DIR
# Cấu hình (kể cả token) nằm trong $DIR/.env, reader tự đọc - unit này không
# mang bí mật nào.
ExecStart=$DIR/.venv/bin/python -m reader
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
)
    if [ "$(cat "$UNIT" 2>/dev/null)" != "$unit" ]; then
        printf '%s\n' "$unit" | as_root tee "$UNIT" >/dev/null || { bad "không ghi được $UNIT"; return; }
        as_root systemctl daemon-reload
        ok "đã ghi $UNIT"
    fi

    # Reader chạy tay kiểu cũ (nohup ./chay.sh) đang giữ cổng thì service
    # không lên được, và lỗi "Address already in use" chỉ hiện trong journal.
    if ! systemctl is-active --quiet reader && pgrep -f "python -m reader" >/dev/null; then
        pkill -f "python -m reader" && sleep 1 && note "đã dừng reader đang chạy tay (nohup)"
    fi

    as_root systemctl enable --quiet reader
    as_root systemctl restart reader
    sleep 3
    if systemctl is-active --quiet reader; then
        ok "service reader đang chạy"
    else
        bad "service reader không lên - xem: journalctl -u reader -n 50"
    fi
}

if [ "$SERVICE" = 1 ] && [ "$MODE" != "check" ]; then
    head1 "Service systemd"
    install_service
elif [ "$MODE" = "check" ] && command -v systemctl >/dev/null && [ -f "$UNIT" ]; then
    head1 "Service systemd"
    systemctl is-active --quiet reader && ok "service reader đang chạy" \
        || bad "service reader không chạy - xem: journalctl -u reader -n 50"
fi

# ---------------------------------------------------------------- 7. kết quả
head1 "Kết quả"
[ "$warn" -eq 0 ] && echo "  Không có vấn đề nào." || echo "  $warn vấn đề ở trên."

ip=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<NEXT

Mở: http://${ip:-<ip>}:$(envval READER_PORT | grep . || echo 5678)/?token=$(envval READER_TOKEN)

NEXT
if [ -f "$UNIT" ]; then
    cat <<'NEXT'
  journalctl -u reader -f           # xem log
  sudo systemctl restart reader     # sau khi sửa .env
  ./setup.sh --update               # kéo bản mới về và khởi động lại
NEXT
else
    cat <<'NEXT'
  ./setup.sh --service              # chạy nền bằng systemd, tự lên lại sau reboot
  uv run python -m reader           # hoặc chạy thẳng ở terminal này
NEXT
fi
[ "$warn" -eq 0 ]
