FROM python:3.11-slim

WORKDIR /app

# 先复制依赖清单以利用构建缓存
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 复制后端与前端代码
COPY backend/app /app/app
COPY frontend /app/frontend
COPY .env.example /app/.env.example

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
