# CS2HQ 后端镜像：Python 3.12 slim + 锁版依赖
FROM python:3.12-slim

WORKDIR /app

# RapidOCR（opencv-python）运行时系统依赖：libxcb/libGL/libglib；curl 为 healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb1 libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

# 先拷贝清单利用层缓存（requirements 全部 == 锁版）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# vendored 签名 wheel（完美 demo 直下：cs_demo_pwa_signer）
COPY vendor /tmp/vendor
RUN pip install --no-cache-dir /tmp/vendor/*.whl && rm -rf /tmp/vendor

COPY app ./app

# 数据目录（DB/日志/凭证），由 compose 卷挂载持久化
RUN mkdir -p /app/data
ENV CS2HQ_DATA_DIR=/app/data

EXPOSE 8101
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8101"]
