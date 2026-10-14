#!/usr/bin/env bash
# Khởi chạy reader.
#
#   ./run.sh              chạy trực tiếp ở terminal (Ctrl+C để dừng)
#   ./run.sh --daemon     chạy nền (background)
#   ./run.sh --stop       dừng tiến trình đang chạy nền
#   ./run.sh --status     kiểm tra tiến trình đang chạy hay dừng
#   ./run.sh --log        xem log thời gian thực
#   ./run.sh [args...]    truyền thêm tham số cho reader (ví dụ: --port 8000, --verbose)
#
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 2
DIR="$(pwd)"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

PID_FILE="$DIR/reader.pid"
LOG_FILE="$DIR/reader.log"
ENV_FILE="$DIR/.env"

envval() {
    [ -f "$ENV_FILE" ] || return 0
    sed -nE "s/^(export )?$1=//p" "$ENV_FILE" | tail -1 \
        | sed -E -e "s/^[[:space:]]*([\"'])(.*)\1[[:space:]]*\$/\2/;t" \
                 -e 's/^[[:space:]]*#.*//' -e 's/[[:space:]]+#.*//' -e 's/^[[:space:]]+//'
}

# 1. Kiểm tra môi trường - nếu chưa có .env hoặc chưa có uv/.venv thì tự gọi ./setup.sh
if [ ! -f "$ENV_FILE" ] || [ ! -d "$DIR/.venv" ] || ! command -v uv >/dev/null 2>&1; then
    echo "== Môi trường chưa được cài đặt đầy đủ. Đang tự động chạy ./setup.sh... =="
    if [ -f "$DIR/setup.sh" ]; then
        bash "$DIR/setup.sh" || { echo "Setup thất bại!" >&2; exit 1; }
    else
        echo "LỖI: Không tìm thấy setup.sh!" >&2
        exit 1
    fi
fi

# 2. Xử lý các lệnh quản lý tiến trình phụ trợ
case "${1:-}" in
    --stop)
        stopped=0
        if [ -f "$PID_FILE" ]; then
            pid=$(cat "$PID_FILE" 2>/dev/null || true)
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null && rm -f "$PID_FILE"
                echo "Đã dừng reader (PID $pid)."
                stopped=1
            fi
            rm -f "$PID_FILE"
        fi
        if pgrep -f "python -m reader" >/dev/null 2>&1; then
            pkill -f "python -m reader" && echo "Đã dừng các tiến trình reader."
            stopped=1
        fi
        if [ "$stopped" -eq 0 ]; then
            echo "Reader không đang chạy."
        fi
        exit 0
        ;;
    --status)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
            pid=$(cat "$PID_FILE")
            port=$(envval READER_PORT); port=${port:-5678}
            token=$(envval READER_TOKEN)
            echo "Reader đang chạy ở chế độ background (PID: $pid)."
            echo "URL: http://localhost:${port}/?token=${token}"
            exit 0
        elif pgrep -f "python -m reader" >/dev/null 2>&1; then
            echo "Reader đang chạy (tiến trình hệ thống hoặc terminal khác)."
            port=$(envval READER_PORT); port=${port:-5678}
            token=$(envval READER_TOKEN)
            echo "URL: http://localhost:${port}/?token=${token}"
            exit 0
        else
            echo "Reader hiện không chạy."
            exit 1
        fi
        ;;
    --log)
        [ -f "$LOG_FILE" ] || touch "$LOG_FILE"
        exec tail -f "$LOG_FILE"
        ;;
esac

PORT=$(envval READER_PORT); PORT=${PORT:-5678}
TOKEN=$(envval READER_TOKEN)
HOST=$(envval READER_HOST); HOST=${HOST:-0.0.0.0}
IP=$(hostname -I 2>/dev/null | awk '{print $1}')

print_banner() {
    cat <<BANNER

============================================================
                    READER ĐANG CHẠY
============================================================
  Truy cập giao diện:
    http://localhost:${PORT}/?token=${TOKEN}
BANNER
    if [ -n "$IP" ] && [ "$HOST" = "0.0.0.0" ]; then
        cat <<BANNER
    http://${IP}:${PORT}/?token=${TOKEN}
BANNER
    fi
    cat <<BANNER
============================================================
BANNER
}

# 3. Chạy nền (--daemon / -d / --background)
if [ "${1:-}" = "--daemon" ] || [ "${1:-}" = "-d" ] || [ "${1:-}" = "--background" ]; then
    shift
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
        echo "Reader đã đang chạy với PID $(cat "$PID_FILE")."
        echo "Dừng lại: ./run.sh --stop"
        exit 0
    fi
    nohup uv run python -m reader "$@" >> "$LOG_FILE" 2>&1 &
    NEW_PID=$!
    echo "$NEW_PID" > "$PID_FILE"
    sleep 1
    if kill -0 "$NEW_PID" 2>/dev/null; then
        print_banner
        echo "  Chế độ: Chạy nền (PID: $NEW_PID)"
        echo "  Log:    $LOG_FILE (xem bằng: ./run.sh --log)"
        echo "  Dừng:   ./run.sh --stop"
        echo "============================================================"
        exit 0
    else
        echo "Khởi động reader thất bại! Xem log:"
        tail -n 20 "$LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
fi

# 4. Chạy trực tiếp (Foreground)
print_banner
echo "  Nhấn Ctrl+C để dừng."
echo "============================================================"
echo

exec uv run python -m reader "$@"
