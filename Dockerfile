# Multi-stage Dockerfile for NotebookFlow on Google Cloud Run

# Stage 1: Build React Production Assets
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Python Backend with Headless Chromium for PDF rendering
FROM python:3.11-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    ENVIRONMENT=production

# Install essential system tools for Playwright dependency installer
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements and Playwright with Linux Chromium dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r backend/requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled frontend assets from Stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Copy backend application code
COPY backend ./backend
COPY index.html ./

EXPOSE 8000

# Cloud Run injects $PORT dynamically; run uvicorn on $PORT
CMD ["sh", "-c", "python -m uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
