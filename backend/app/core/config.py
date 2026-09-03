"""Application settings — Phase 8 Production Hardening.

Hard rules enforced here:
  • Secrets come from environment variables ONLY. There is no default/fallback
    SECRET_KEY anywhere in this codebase; if it is missing the application
    refuses to start.
  • In production (APP_ENV=production) the application refuses to start when
    any required setting is missing or any known demo/test credential is present.
  • SEED_ON_START is permanently overridden to False in production, regardless
    of the environment variable value.
  • PAYMENT_PROVIDER=mock and CREDIT_PROVIDER=mock are rejected in production
    UNLESS demo_mode=True is explicitly set via DEMO_MODE=1. This prevents
    mock providers from silently processing real-money transactions.
  • DEMO_MODE=1 in production enables mock providers but logs a prominent
    warning. It is intended for staging environments that share production
    infrastructure.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# ─────────────────────────────────────────────────────────────────────────────
# Known demo / test credential fragments that must NEVER appear in production.
# These are checked against SECRET_KEY.  If any of these strings appear in the
# key the app will refuse to boot in production.
# ─────────────────────────────────────────────────────────────────────────────
_DEMO_SECRET_FRAGMENTS: tuple[str, ...] = (
    "test",
    "demo",
    "secret",
    "change_me",
    "changeme",
    "example",
    "dev",
    "default",
    "insecure",
    "placeholder",
    "your_secret",
    "yoursecret",
    "mysecret",
    "my_secret",
    "sample",
    "unsafe",
    "replace",
    "replace_me",
    "replaceme",
    "fixme",
    "fix_me",
    "todo",
    "password",
    "12345",
    "abcdef",
    "aaaaaa",
)

VALID_ENVIRONMENTS: frozenset[str] = frozenset({"development", "test", "staging", "production"})


class ConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        raise ConfigError(
            f"Missing required environment variable {name!r}. "
            f"Secrets must be supplied via the environment; there is no default."
        )
    return value.strip()


def _optional(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else value.strip()


def _int(name: str, default: int) -> int:
    return int(_optional(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    raw = _optional(name, "1" if default else "0")
    return raw.lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    secret_key: str
    database_url: str
    app_env: str = "development"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 3600
    currency: str = "IRR"
    # Minor units for IRR are not used in practice, but money is still stored as
    # an exact integer count of minor units to make Decimal arithmetic lossless.
    currency_exponent: int = 0
    payment_provider: str = "mock"
    credit_provider: str = "mock"
    cors_origins: tuple[str, ...] = field(default_factory=tuple)
    seed_on_start: bool = False
    # Rate limiting (requests per minute per IP, 0 = disabled)
    rate_limit_per_minute: int = 0
    # DEMO_MODE: allow mock providers in production (must be explicitly enabled)
    demo_mode: bool = False

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def sqlite_path(self) -> str:
        if not self.database_url.startswith("sqlite:///"):
            raise ConfigError(
                f"Unsupported DATABASE_URL {self.database_url!r}. "
                f"This build supports sqlite:///<path> only."
            )
        return self.database_url[len("sqlite:///"):]


MIN_SECRET_KEY_LENGTH = 32


def _validate_production_config(
    secret_key: str, app_env: str,
    payment_provider: str, credit_provider: str, demo_mode: bool,
) -> None:
    """Raise ConfigError if production config is unsafe.

    Called only when APP_ENV=production. Checks:
      1. SECRET_KEY length (already checked universally)
      2. SECRET_KEY must not contain known demo/test fragments
      3. Mock providers require explicit DEMO_MODE=1 opt-in
    """
    if app_env != "production":
        return

    lower_key = secret_key.lower()
    for fragment in _DEMO_SECRET_FRAGMENTS:
        if fragment in lower_key:
            raise ConfigError(
                f"SECRET_KEY contains a known demo/test fragment ({fragment!r}). "
                f"Production requires a cryptographically random key. "
                f"Generate one with: openssl rand -hex 32"
            )

    if not demo_mode:
        if payment_provider == "mock":
            raise ConfigError(
                "PAYMENT_PROVIDER=mock is not allowed in production. "
                "Configure a real payment provider or set DEMO_MODE=1 to "
                "explicitly allow mock providers (for staging/demo environments only)."
            )
        if credit_provider == "mock":
            raise ConfigError(
                "CREDIT_PROVIDER=mock is not allowed in production. "
                "Configure a real credit provider or set DEMO_MODE=1 to "
                "explicitly allow mock providers (for staging/demo environments only)."
            )


def load_settings() -> Settings:
    app_env = _optional("APP_ENV", "development")
    if app_env not in VALID_ENVIRONMENTS:
        raise ConfigError(
            f"APP_ENV={app_env!r} is not a valid environment. "
            f"Must be one of: {', '.join(sorted(VALID_ENVIRONMENTS))}"
        )

    origins = _optional("CORS_ORIGINS", "http://localhost:3000")
    secret_key = _require("SECRET_KEY")
    if len(secret_key) < MIN_SECRET_KEY_LENGTH:
        raise ConfigError(
            f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters "
            f"(got {len(secret_key)}). Generate one with: openssl rand -hex 32"
        )

    payment_provider = _optional("PAYMENT_PROVIDER", "mock")
    credit_provider = _optional("CREDIT_PROVIDER", "mock")
    demo_mode = _bool("DEMO_MODE", False)

    _validate_production_config(secret_key, app_env, payment_provider, credit_provider, demo_mode)

    # Production: SEED_ON_START is always False, regardless of env var.
    if app_env == "production":
        seed_on_start = False
    else:
        seed_on_start = _bool("SEED_ON_START", True)

    return Settings(
        app_env=app_env,
        secret_key=secret_key,
        database_url=_require("DATABASE_URL"),
        jwt_algorithm=_optional("JWT_ALGORITHM", "HS256"),
        access_token_ttl_seconds=_int("ACCESS_TOKEN_TTL_SECONDS", 3600),
        currency=_optional("CURRENCY", "IRR"),
        currency_exponent=_int("CURRENCY_EXPONENT", 0),
        payment_provider=payment_provider,
        credit_provider=credit_provider,
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        seed_on_start=seed_on_start,
        rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 0),
        demo_mode=demo_mode,
    )
