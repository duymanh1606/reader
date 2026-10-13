FROM python:3.12-slim

# Cài uv từ image chính thức
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Thiết lập biến môi trường
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH="/app/.venv/bin:$PATH" \
    READER_HOST=0.0.0.0 \
    READER_PORT=5678 \
    READER_HEADLESS=true \
    READER_BROWSER_CHANNEL=""

WORKDIR /app

# Copy dependency files trước để tận dụng Docker cache
COPY pyproject.toml uv.lock ./

# Cài đặt Python packages và Chromium cùng các thư viện hệ thống cần thiết
RUN uv sync --frozen --no-dev && \
    uv run playwright install --with-deps chromium && \
    rm -rf /var/lib/apt/lists/*

# Copy mã nguồn ứng dụng
COPY reader /app/reader

# Thư mục lưu trữ session profiles của Outlook
VOLUME ["/app/.profiles"]

EXPOSE 5678

CMD ["python", "-m", "reader"]

