FROM python:3.12-slim AS backend

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
COPY api/ api/
COPY cli.py config.py ./

RUN pip install --no-cache-dir ".[dev]" fastapi uvicorn python-multipart

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM node:18-slim AS frontend-build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build


FROM python:3.12-slim

WORKDIR /app

# Backend
COPY pyproject.toml .
COPY src/ src/
COPY api/ api/
COPY cli.py config.py ./
RUN pip install --no-cache-dir ".[dev]" fastapi uvicorn python-multipart

# Frontend build estático
COPY --from=frontend-build /app/dist /app/static

# Volumes
VOLUME /app/db

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
