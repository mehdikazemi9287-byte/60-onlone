FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/backend

COPY requirements.txt requirements-pg.txt ./
# Slow links to pypi.org (e.g. from Iranian datacenters): longer timeout and more retries
ARG PIP_DEFAULT_TIMEOUT=120
ARG PIP_RETRIES=10
# Optional PyPI index override, passed at build time (default: pypi.org)
ARG PIP_INDEX_URL=https://pypi.org/simple
# requirements.txt includes Pillow (admin image upload); its manylinux wheel needs no system packages on
# python:3.11-slim. After any requirements change, rebuild this image: an old image has no Pillow.
RUN pip install --no-cache-dir -r requirements.txt -r requirements-pg.txt

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
