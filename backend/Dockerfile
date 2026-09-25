FROM python:3.12-slim

WORKDIR /app

# 系统依赖（PyMuPDF 等 wheel 自带，无需额外系统库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 先拷依赖清单以利用 Docker 层缓存
COPY pyproject.toml ./
RUN uv sync --no-dev

# 拷业务代码
COPY . .

# 上传目录（与 docker-compose 卷挂载一致）
RUN mkdir -p /app/uploads
ENV UPLOAD_DIR=/app/uploads

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
