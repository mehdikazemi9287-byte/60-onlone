"""JWT Revocation Service — Blocker 4.

Stores revoked token JTIs so that logout and role/password-change invalidation
take effect immediately, before the token's natural expiry.

Design:
  - revoked_tokens table (migration 0022) holds jti, user_id, expires_at.
  - A token is rejected if its jti appears in the table.
  - Expired revocation records are cleaned up to keep the table small.
  - User-wide revocation (after password or role change) is done by storing
    a special sentinel jti that represents "all tokens issued before this time".
    We do this by storing a per-user invalidation timestamp in a separate column
    on the revoked_tokens table. Instead, we store the actual jti for individual
    revocations and use a `invalidated_before` approach via the users table.

Simplified approach (no extra column needed):
  - Logout: insert the specific jti into revoked_tokens.
  - Password/role change: call invalidate_all_tokens_for_user() which inserts
    a sentinel row with jti='*' + user_id marker — actually we just set a
    user-level invalidated_before timestamp. We store this in users table by
    adding a column... but we cannot add a column without a migration.

Instead, use a clean approach:
  - Store per-jti revocations for logout.
  - For user-wide invalidation: store one row per user with a special jti
    pattern so is_revoked() can check it. We use jti='REVOKED_ALL:<user_id>:<timestamp>'
    but that's fragile. Better: store a special sentinel that is checked by the
    decode path.

CLEANEST APPROACH (chosen):
  - revoked_tokens holds individual jti values.
  - For user-wide invalidation: we add a `token_invalidated_at` column in
    migration 0022 or store it as a special row. Since we already have the
    migration, we'll use a separate table-based approach:
    Insert a row with jti = user_scope_key(user_id, timestamp) that marks
    "all tokens issued before timestamp for user X are revoked."
    The is_revoked() check queries both the jti directly AND checks the
    user-scope sentinel.

ACTUAL IMPLEMENTATION:
  - revoked_tokens stores individual jti values.
  - users table is updated with token_invalidated_at via ALTER TABLE in migration 0022
    (already done in the SQL migration above — but we didn't add that column).

Since migration 0022 only adds revoked_tokens table (not a column on users),
we implement user-wide invalidation by inserting ALL active token jtis... which
we don't track. Instead:

FINAL APPROACH: Add a `token_generation` integer to users. Increment it on
password/role change. Embed `tgen` in the JWT payload. Check in authenticate_request().
This requires no extra table and is O(1) to verify.

But that requires changing the JWT payload structure and the current tokens
already in circulation won't have tgen. For now, the simplest correct approach:

User-wide invalidation = mark timestamp in a dedicated small table keyed by user_id.
revoked_tokens already exists. We use a special jti format '*:<user_id>' to store
the cutoff timestamp in expires_at field... no, that's confusing.

IMPLEMENTED APPROACH:
  - Logout: store specific jti in revoked_tokens.
  - User-wide: store a row with jti='USERINVALIDATE:<user_id>', no expires_at check.
    is_revoked checks: jti in revoked_tokens OR (user has a USERINVALIDATE row
    with revoked_at > token.iat... but we don't have token.iat here).

SIMPLEST CORRECT: Store user_token_generation in a separate table, embed in JWT.
Since we're already writing new tokens, new tokens will have tgen=current, and
old tokens without tgen field will be rejected by the generation check.

Given scope, we implement:
  1. Specific jti revocation (logout)
  2. User-wide invalidation by storing timestamp; reject tokens issued before it.
     JWT TokenClaims has `expires_at` but not `issued_at`. We store issued_at
     in the JWT ('iat' field) — decode already reads it (it's in the payload).
     We need to expose iat from decode_access_token.

DECISION: Extend TokenClaims to include issued_at, store user cutoff in DB.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.db import Database

logger = logging.getLogger(__name__)

_SENTINEL_PREFIX = "USERINVALIDATE:"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def revoke_token(db: Database, *, jti: str, user_id: int, expires_at: int) -> None:
    """Revoke a specific token by JTI.

    Idempotent — inserting the same jti twice is a no-op (UNIQUE constraint).
    expires_at is the Unix timestamp when the token expires; used for cleanup.
    """
    expires_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()
    with db.write_transaction() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO revoked_tokens (jti, user_id, revoked_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (jti, user_id, _now_iso(), expires_iso),
        )


def invalidate_all_tokens_for_user(db: Database, *, user_id: int) -> None:
    """Invalidate ALL currently-issued tokens for a user.

    Implemented by writing a sentinel row keyed to (USERINVALIDATE:<user_id>).
    The expires_at is set far in the future so cleanup doesn't remove it prematurely.
    The revoked_at timestamp records when the invalidation occurred.

    During authentication, is_token_valid() checks whether a token was issued
    BEFORE this sentinel's revoked_at. If so, the token is rejected.
    """
    sentinel_jti = f"{_SENTINEL_PREFIX}{user_id}"
    # Far-future expiry so the sentinel survives until manually cleared.
    expires_iso = "2099-12-31T23:59:59+00:00"
    now = _now_iso()
    with db.write_transaction() as conn:
        conn.execute(
            """
            INSERT INTO revoked_tokens (jti, user_id, revoked_at, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(jti) DO UPDATE SET revoked_at=excluded.revoked_at
            """,
            (sentinel_jti, user_id, now, expires_iso),
        )


def is_token_revoked(db: Database, *, jti: str, user_id: int, issued_at: int) -> bool:
    """Return True if the token should be rejected.

    Checks:
      1. The specific JTI is in revoked_tokens.
      2. A user-wide invalidation sentinel exists with revoked_at AFTER the
         token's issued_at (meaning all tokens issued before the sentinel are invalid).
    """
    # Check specific JTI
    row = db.query_one(
        "SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,)
    )
    if row is not None:
        return True

    # Check user-wide invalidation sentinel
    sentinel_jti = f"{_SENTINEL_PREFIX}{user_id}"
    sentinel = db.query_one(
        "SELECT revoked_at FROM revoked_tokens WHERE jti = ?", (sentinel_jti,)
    )
    if sentinel is not None:
        # Token is revoked if it was issued before the sentinel was created
        revoked_at_str = sentinel["revoked_at"]
        try:
            # Parse the ISO string; may or may not have timezone info
            revoked_ts = datetime.fromisoformat(revoked_at_str)
            if revoked_ts.tzinfo is None:
                revoked_ts = revoked_ts.replace(tzinfo=timezone.utc)
            revoked_unix = int(revoked_ts.timestamp())
            if issued_at < revoked_unix:
                return True
        except (ValueError, TypeError):
            # Malformed timestamp — fail safe, reject the token
            logger.error("revocation: malformed revoked_at for sentinel user_id=%d", user_id)
            return True

    return False


def cleanup_expired_revocations(db: Database) -> int:
    """Remove revocation records whose token has already expired.

    Returns the number of rows deleted.
    Sentinels (USERINVALIDATE:*) have far-future expiry and won't be deleted.
    """
    now = _now_iso()
    with db.write_transaction() as conn:
        cur = conn.execute(
            "DELETE FROM revoked_tokens WHERE expires_at < ? AND jti NOT LIKE ?",
            (now, f"{_SENTINEL_PREFIX}%"),
        )
        return cur.rowcount
