FROM python:3.12-slim

WORKDIR /app

# 离线抓取下厨房需要的基础库（curl 用于容器内 HEALTHCHECK 备用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY xcf2mealie.py app.py healthcheck.py ./

# 默认端口（可在 docker run -e PORT=xxxx 或 compose environment 覆盖）
ENV PORT=9926 \
    PYTHONUNBUFFERED=1 \
    DEFAULT_TAG=下厨房

EXPOSE 9926

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
    CMD python healthcheck.py || exit 1

CMD ["python", "app.py"]
