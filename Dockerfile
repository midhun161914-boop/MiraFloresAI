# Single image: build the React UI, then serve UI + API from FastAPI.
FROM node:22-alpine AS ui
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY okafor_lindqvist_2025_packet.json ./
COPY --from=ui /app/frontend/dist frontend/dist
ENV PYTHONUNBUFFERED=1
WORKDIR /app/backend
EXPOSE 8000
# Container hosts (Render/Railway/Fly) inject $PORT; default 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
