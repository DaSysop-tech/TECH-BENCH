# syntax=docker/dockerfile:1
# Container listen is 0.0.0.0 *inside* the netns. Publish loopback-only:
#   docker build -t tech-bench .
#   docker run --rm -p 127.0.0.1:8000:8000 -v techbench-data:/app/data tech-bench

FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    TECHBENCH_HOST=0.0.0.0 \
    TECHBENCH_ALLOW_LAN=1 \
    TECHBENCH_PORT=8000
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY agent ./agent
COPY run.py .
COPY --from=ui /ui/dist ./frontend/dist
EXPOSE 8000
CMD ["python", "run.py"]
