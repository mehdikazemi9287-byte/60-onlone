"""فید فقط‌خواندنی وامبی (سرور به سرور).

  GET /api/v1/feeds/vambi/products?updated_since=<ISO-8601>&cursor=<opaque>&limit=<1..500>
  Authorization: Bearer <VAMBI_FEED_TOKEN>

Off (404) until VAMBI_FEED_TOKEN is set. VAMBI_FEED_TOKEN may hold several comma-separated tokens (rotation);
each must be at least 32 characters. Rate limit per token: VAMBI_FEED_RATE_PER_MIN (default 60).
The contract (tiers, cursor, tombstones) is in services/vambi_feed_service.py and docs/integrations/vambi-feed.md.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading

from flask import Blueprint, jsonify, request

from app.core.deps import get_db
from app.core.errors import ApiError, AuthenticationError, NotFoundError
from app.core.rate_limiter import InMemoryRateLimiter
from app.services import vambi_feed_service as feed

bp = Blueprint("vambi_feed", __name__, url_prefix="/api/v1/feeds/vambi")
MIN_TOKEN_LEN = 32
_limiters: dict = {}
_lock = threading.Lock()


class FeedRateLimited(ApiError):
    status_code = 429
    code = "rate_limit_exceeded"


def _tokens() -> list[str]:
    raw = os.environ.get("VAMBI_FEED_TOKEN", "")
    return [t.strip() for t in raw.split(",") if len(t.strip()) >= MIN_TOKEN_LEN]


def _authenticate() -> str:
    """Return a stable, non-secret id of the matching token (for the rate-limit bucket)."""
    tokens = _tokens()
    if not tokens:
        raise NotFoundError("not found", code="vambi_feed_disabled")
    header = request.headers.get("Authorization", "")
    given = header[7:].strip() if header.startswith("Bearer ") else ""
    match = None
    for t in tokens:  # compare against every token, constant time each
        if given and hmac.compare_digest(given.encode(), t.encode()):
            match = t
    if match is None:
        raise AuthenticationError("توکن فید نامعتبر است", code="invalid_feed_token")
    return hashlib.sha256(match.encode()).hexdigest()[:16]


def _rate_limit(token_id: str) -> None:
    try:
        per_min = max(1, int(os.environ.get("VAMBI_FEED_RATE_PER_MIN", "60")))
    except ValueError:
        per_min = 60
    with _lock:
        lim = _limiters.get((token_id, per_min))
        if lim is None:
            lim = _limiters[(token_id, per_min)] = InMemoryRateLimiter(per_min, 60)
    if not lim.is_allowed(token_id):
        raise FeedRateLimited("تعداد درخواست‌های فید از سقف مجاز بیشتر است",
                              details={"retry_after": lim.retry_after(token_id)})


@bp.get("/products")
def products():
    token_id = _authenticate()
    _rate_limit(token_id)
    since = feed.parse_since(request.args.get("updated_since"))
    cursor = feed.decode_cursor(request.args.get("cursor"))
    limit = feed.parse_limit(request.args.get("limit"))
    with get_db().read_transaction() as conn:
        out = feed.products(conn, updated_since=since, cursor=cursor, limit=limit)
    resp = jsonify(out)
    resp.headers["Cache-Control"] = "no-store"
    return resp
