FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MIRAGE_DB=/data/mirage.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser
COPY . .
RUN mkdir -p /data && chown -R appuser:appuser /app /data

USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=2", "--threads=4", "--timeout=120", "app:app"]
