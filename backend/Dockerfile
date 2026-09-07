FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/backend

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY migrations_postgresql ./migrations_postgresql
COPY recovery ./recovery
COPY scripts ./scripts
COPY tests ./tests
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh && \
    mkdir -p /srv/backend/data && \
    useradd --system --uid 10001 appuser && \
    chown -R appuser:appuser /srv/backend
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).status==200 else 1)"

ENTRYPOINT ["./entrypoint.sh"]
