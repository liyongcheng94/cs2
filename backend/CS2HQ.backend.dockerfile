# CS2HQ 后端镜像：Python 3.12 slim + 锁版依赖
FROM python:3.12-slim

WORKDIR /app

# 先拷贝清单利用层缓存（requirements 全部 == 锁版）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# 数据目录（DB/日志/凭证），由 compose 卷挂载持久化
RUN mkdir -p /app/data
ENV CS2HQ_DATA_DIR=/app/data

EXPOSE 8101
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8101"]
