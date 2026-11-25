# 有谱掌柜部署用镜像
# 与本地 .venv 同版本线（Python 3.14，requirements.txt 在其上实测解析）
FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite 与备份落在 /data（fly.io 持久卷挂载点；本地 docker 跑也要 -v 一个卷）
RUN mkdir -p /data
ENV CLERK_DB=/data/clerk.db

EXPOSE 8100
# 单进程：SQLite 写串行最简单可靠（docs/33 的纪律在容器里同样成立）
CMD ["python", "-m", "uvicorn", "clerk.server:app", "--host", "0.0.0.0", "--port", "8100"]
