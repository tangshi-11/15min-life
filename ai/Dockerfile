# 15分钟生活圈 · AI 解读服务（可选加分模块，CPU 推理）
# 构建：docker build -f ai/Dockerfile -t 15min-life-ai .
# 模型目录（ai/models/，含 Qwen2.5-1.5B-Instruct 与 qwen15min-lora）不入镜像，
# 需按 docs/模型训练教程.md 准备后以 volume 挂载：-v ./ai/models:/app/models
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# CPU 版 torch（避免 CUDA 依赖，控制镜像体积）
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY ai/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY ai/server.py /app/server.py

VOLUME /app/models
EXPOSE 8001

# fp32 精度（CPU 不支持 bf16 算子）；模型由外部 volume 提供
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8001", "--dtype", "fp32"]
