FROM node:22-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends bash procps curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" websockets psutil
COPY backend/ /app/backend/
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist
ENV PYTHONUNBUFFERED=1 WORKSPACE_DIR=/workspace ANTIGRAVITY_CLI_DIR=/home/developer/.gemini/antigravity-cli AGY_BIN=/usr/local/bin/agy
EXPOSE 6767
CMD ["python3", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "6767"]
