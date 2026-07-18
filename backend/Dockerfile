# Cloud Run image. Single stage, small surface, non-root.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY static ./static

RUN useradd -m appuser && chown -R appuser /app
USER appuser

ENV PORT=8080 DB_PATH=/tmp/audit.db
EXPOSE 8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
