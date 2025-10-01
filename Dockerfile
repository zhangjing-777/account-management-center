# 基础镜像：Python 3.11
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 复制依赖
COPY requirements.txt .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码（假设主代码都在当前目录）
COPY . .

# 设置环境变量（可选）
ENV PYTHONUNBUFFERED=1

# 暴露端口（FastAPI 默认 8000）
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]