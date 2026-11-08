"""WSGI entry for production: `gunicorn app.wsgi:app` (see entrypoint.sh, docs/DEPLOY.md)."""
from app.main import create_app

app = create_app()
