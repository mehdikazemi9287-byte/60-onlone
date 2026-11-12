"""Flask application factory (modular monolith, single deployable)."""

from __future__ import annotations

import logging
import time

from flask import Flask, current_app, g, jsonify, request

from app.api.v1 import customer_requests as customer_requests_api
from app.api.v1 import auth as auth_api
from app.api.v1 import cart as cart_api
from app.api.v1 import catalog as catalog_api
from app.api.v1 import credit as credit_api
from app.api.v1 import health as health_api
from app.api.v1 import logistics as logistics_api
from app.api.v1 import orders as orders_api
from app.api.v1 import organizations as organizations_api
from app.api.v1 import settlement as settlement_api
from app.api.v1 import suppliers as suppliers_api
from app.api.v1 import master_catalog as master_catalog_api
from app.api.v1 import procurement as procurement_api
from app.api.v1 import enterprise_procurement as enterprise_procurement_api
from app.api.v1 import admin_product_content as admin_product_content_api
from app.api.v1 import admin_product_identity as admin_product_identity_api
from app.api.v1 import admin_taxonomy as admin_taxonomy_api
from app.api.v1 import admin_console as admin_console_api
from app.api.v1 import admin_media as admin_media_api
from app.api.v1 import admin_content as admin_content_api
from app.api.v1 import admin_dashboard as admin_dashboard_api
from app.api.v1 import access_admin as access_admin_api
from app.api.v1 import marketplace as marketplace_api
from app.api.v1 import commerce_ops as commerce_ops_api
from app.api.v1 import organization_operations as organization_operations_api
from app.api.v1 import customer_workflow as customer_workflow_api
from app.api.v1 import organization_finance_policy as organization_finance_policy_api

# Phase 6 — Inventory Intelligence + Product Identifiers + ERP/Store Connector
from app.api.v1 import identifiers as identifiers_api
from app.api.v1 import inventory_sources as inventory_sources_api
from app.api.v1 import price_sources as price_sources_api
from app.api.v1 import connectors as connectors_v6_api
from app.api.v1 import sync_runs as sync_runs_api
from app.api.v1 import erp_mappings as erp_mappings_api
from app.api.v1 import import_jobs as import_jobs_api
from app.api.v1 import scanner as scanner_api

# Phase 6 Final — Exception inbox, Invoices, Reconciliation, Discovery
from app.api.v1 import exceptions as exceptions_api
from app.api.v1 import invoices as invoices_api
from app.api.v1 import reconciliation as reconciliation_api
from app.api.v1 import discovery as discovery_api

# Phase 7 — Enterprise Integration & Automation Hub
from app.api.v1 import integration_events as integration_events_api
from app.api.v1 import tax as tax_api
from app.api.v1 import accounting_connectors as accounting_connectors_api
from app.api.v1 import connector_wizard as connector_wizard_api

# Loyalty foundation — 60Coin (structurally separate from credit/ledger)
from app.api.v1 import loyalty as loyalty_api
from app.api.v1 import admin_supplier_profile, admin_image_review, saved_pack_drafts, admin_catalog_sources
from app.api.v1 import seller_shops as seller_shops_api
from app.api.v1 import cashier as cashier_api
from app.api.v1 import org_brands as org_brands_api
from app.api.v1 import credit_platform as credit_platform_api
from app.api import partner_v1 as partner_v1_api
from app.api.v1 import consumer_rights as consumer_rights_api
from app.api.v1 import in_person as in_person_api
from app.api.v1 import seller_direct as seller_direct_api
from app.api.v1 import affiliates as affiliates_api
from app.api.v1 import catalog_schema as catalog_schema_api
from app.api.v1 import price_feeds as price_feeds_api
from app.api.v1 import vambi as vambi_api
from app.api.v1 import b2b as b2b_api
from app.api.v1 import price_alerts as price_alerts_api
from app.api.v1 import retail_network as retail_network_api
from app.api.v1 import admin_partner_api, finance_exports as finance_exports_api, logistics_v2 as logistics_v2_api
from app.core.config import Settings, load_settings
from app.core.db import Database, DatabaseBackend, make_backend
from app.core.errors import ApiError
from app.core.secret_resolver import FailClosedSecretResolver, SecretResolver
from app.core.logging_config import configure_logging
from app.core.metrics import InMemoryMetricsCollector, NoOpMetricsCollector
from app.core.rate_limiter import FailClosedRateLimiter, InMemoryRateLimiter, NoOpRateLimiter

logger = logging.getLogger("60online")


def create_app(
    settings: Settings | None = None,
    database: DatabaseBackend | None = None,
    secret_resolver: SecretResolver | None = None,
) -> Flask:
    settings = settings or load_settings()
    database = database or make_backend(settings.database_url)

    # Default to FailClosedSecretResolver so any code path that calls
    # resolve() without a real backend configured fails loudly.
    if secret_resolver is None:
        secret_resolver = FailClosedSecretResolver()

    # Configure structured logging early — JSON in staging/production
    json_logs = settings.app_env in ("staging", "production")
    log_level = "INFO" if settings.app_env in ("staging", "production") else "DEBUG"
    configure_logging(level=log_level, json_output=json_logs)

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.config["TEST_SALES_OVERRIDE"] = settings.app_env == "test"
    app.extensions["settings"] = settings
    app.extensions["db"] = database

    if settings.payment_provider == "sepehr":
        from app.adapters.payment import registry as payment_registry
        from app.adapters.payment.sepehr import SepehrPaymentProvider
        payment_registry.register(SepehrPaymentProvider(settings.sepehr_terminal_id))

    # External credit (Tara pattern): licensed lenders fund the purchase; we only accept it.
    from app.adapters.payment import registry as _payment_registry
    from app.adapters.payment.external_credit import enabled_from_env
    app.extensions["external_credit_providers"] = []
    for _provider in enabled_from_env():
        _payment_registry.register(_provider)
        app.extensions["external_credit_providers"].append(_provider.name)

    # VandaPay («پرداخت با ونداپی»): off unless VANDAPAY_* env is set; live keys only in production.
    from app.adapters.payment.vandapay import enabled_from_env as _vandapay_from_env
    app.extensions["vandapay_provider"] = None
    _vandapay = _vandapay_from_env(app_env=settings.app_env, demo_mode=settings.demo_mode)
    if _vandapay is not None:
        _payment_registry.register(_vandapay)
        app.extensions["vandapay_provider"] = _vandapay.name

    @app.after_request
    def _private_cache_control(response):
        if request.headers.get("Authorization") or request.path.startswith("/api/v1/admin/"):
            response.headers["Cache-Control"]="no-store"
            response.headers["Pragma"]="no-cache"
            response.vary.add("Authorization")
        return response

    app.extensions["secret_resolver"] = secret_resolver

    # ---- Metrics collector -----------------------------------------------
    metrics = InMemoryMetricsCollector()
    app.extensions["metrics"] = metrics

    # ---- Rate limiter ----------------------------------------------------
    if settings.rate_limit_per_minute > 0:
        _inner_limiter = InMemoryRateLimiter(
            requests_per_window=settings.rate_limit_per_minute,
            window_seconds=60,
        )
        rate_limiter = FailClosedRateLimiter(_inner_limiter)
    else:
        rate_limiter = NoOpRateLimiter()
    app.extensions["rate_limiter"] = rate_limiter

    for blueprint in (
        health_api.bp,
        auth_api.bp,
        catalog_api.bp,
        cart_api.bp,
        orders_api.bp,
        credit_api.bp,
        organizations_api.bp,
        suppliers_api.bp,
        master_catalog_api.bp,
        procurement_api.bp,
        enterprise_procurement_api.bp,
        access_admin_api.bp,
        admin_dashboard_api.bp,
        admin_supplier_profile.bp,
        admin_image_review.bp,
        saved_pack_drafts.bp,
        admin_catalog_sources.bp,
        admin_content_api.bp,
        admin_media_api.bp,
        admin_console_api.bp,
        admin_taxonomy_api.bp,
        admin_product_content_api.bp,
        admin_product_identity_api.bp,
        marketplace_api.bp,
        commerce_ops_api.bp,
        organization_operations_api.bp,
        customer_workflow_api.bp,
        organization_finance_policy_api.bp,
        logistics_api.bp,
        settlement_api.bp,
        # Phase 6
        identifiers_api.bp,
        inventory_sources_api.bp,
        price_sources_api.bp,
        connectors_v6_api.bp,
        sync_runs_api.bp,
        erp_mappings_api.bp,
        import_jobs_api.bp,
        scanner_api.bp,
        # Phase 6 Final
        exceptions_api.bp,
        invoices_api.bp,
        reconciliation_api.bp,
        discovery_api.bp,
        # Phase 7
        integration_events_api.bp,
        tax_api.bp,
        accounting_connectors_api.bp,
        connector_wizard_api.bp,
        # Loyalty
        loyalty_api.bp,
        customer_requests_api.bp,
        # Marketplace roadmap
        seller_shops_api.bp,
        cashier_api.bp,
        org_brands_api.bp,
        credit_platform_api.bp,
        partner_v1_api.bp,
        admin_partner_api.bp,
        finance_exports_api.bp,
        logistics_v2_api.bp,
        consumer_rights_api.bp,
        in_person_api.bp,
        seller_direct_api.bp,
        affiliates_api.bp,
        catalog_schema_api.bp,
        price_feeds_api.bp,
        vambi_api.bp,
        b2b_api.bp,
        price_alerts_api.bp,
        retail_network_api.bp,
    ):
        app.register_blueprint(blueprint)

    # ---- Request correlation ID ------------------------------------------
    @app.before_request
    def _stamp_request():
        import uuid

        g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        g.request_start = time.monotonic()

    # ---- Rate limiting ---------------------------------------------------
    @app.before_request
    def _check_rate_limit():
        limiter = current_app.extensions.get("rate_limiter")
        if limiter is None:
            return
        from app.core.deps import client_ip

        ip = client_ip() or "unknown"
        key = f"ip:{ip}"
        if not limiter.is_allowed(key):
            retry = limiter.retry_after(key)
            response = jsonify(
                {
                    "error": {
                        "code": "rate_limit_exceeded",
                        "message": "درخواست‌های شما بیش از حد مجاز است. لطفاً کمی صبر کنید.",
                    }
                }
            )
            response.status_code = 429
            response.headers["Retry-After"] = str(retry)
            return response

    # ---- Content-type enforcement for mutation endpoints ----------------
    @app.before_request
    def _enforce_content_type():
        if request.method in ("POST", "PUT", "PATCH") and request.content_length:
            ct = request.content_type or ""
            # Order documents / delivery evidence are the only multipart uploads.
            upload = request.method == "POST" and request.path.endswith("/documents") and ct.startswith("multipart/form-data")
            # The bank posts the customer's browser back as an ordinary HTML form.
            bank_return = (request.method == "POST" and request.path.startswith("/api/v1/payments/")
                           and request.path.endswith("/callback")
                           and ct.startswith("application/x-www-form-urlencoded"))
            if not ct.startswith("application/json") and not upload and not bank_return:
                return (
                    jsonify(
                        {
                            "error": {
                                "code": "unsupported_media_type",
                                "message": "Content-Type must be application/json",
                            }
                        }
                    ),
                    415,
                )

    # ---- Request-size limits for import/upload endpoints ----------------
    _IMPORT_SIZE_LIMIT = 10 * 1024 * 1024  # 10 MB
    _DEFAULT_SIZE_LIMIT = 1 * 1024 * 1024  # 1 MB
    _DOCUMENT_SIZE_LIMIT = 6 * 1024 * 1024  # 5 MB file + multipart overhead

    @app.before_request
    def _enforce_request_size():
        cl = request.content_length
        if cl is None:
            return
        limit = _IMPORT_SIZE_LIMIT if "/import" in request.path else (
            _DOCUMENT_SIZE_LIMIT if request.path.endswith("/documents") else _DEFAULT_SIZE_LIMIT)
        if cl > limit:
            return (
                jsonify(
                    {
                        "error": {
                            "code": "payload_too_large",
                            "message": f"Request body exceeds {limit // 1024} KB limit",
                        }
                    }
                ),
                413,
            )

    # ---- CORS (explicit allowlist, no wildcard with credentials) ----------
    @app.after_request
    def apply_cors(response):
        origin = request.headers.get("Origin")
        if origin and origin in settings.cors_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, Idempotency-Key, X-Request-ID, X-Supplier-Id"
            )
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
            response.headers["Access-Control-Max-Age"] = "600"
        return response

    # ---- HTTP metrics instrumentation -----------------------------------
    @app.after_request
    def _record_http_metrics(response):
        m = current_app.extensions.get("metrics")
        if m is not None:
            endpoint = request.endpoint or "unknown"
            method = request.method
            status = str(response.status_code)
            m.increment(
                "http_requests_total",
                labels={"method": method, "endpoint": endpoint, "status": status},
            )
            if hasattr(g, "request_start"):
                duration_ms = (time.monotonic() - g.request_start) * 1000
                m.record(
                    "http_request_duration_ms",
                    duration_ms,
                    labels={"method": method, "endpoint": endpoint},
                )
            if response.status_code >= 500:
                m.increment("http_errors_total", labels={"method": method, "endpoint": endpoint})
        return response

    # ---- Security headers ------------------------------------------------
    from app.core.price_privacy import install as _install_price_privacy
    _install_price_privacy(app)

    @app.after_request
    def apply_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"  # modern browsers use CSP
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains; preload"
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # Expose correlation ID to caller
        if hasattr(g, "request_id"):
            response.headers["X-Request-ID"] = g.request_id
        return response

    # Flask answers OPTIONS automatically for every registered rule, and
    # apply_cors above attaches the preflight headers. A catch-all OPTIONS
    # route is deliberately NOT registered: it would shadow unknown paths and
    # turn their 404 into a 405.

    # ---- error handling ---------------------------------------------------
    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return jsonify(exc.to_dict()), exc.status_code

    @app.errorhandler(404)
    def handle_404(_exc):
        return jsonify({"error": {"code": "not_found", "message": "مسیر مورد نظر یافت نشد"}}), 404

    @app.errorhandler(405)
    def handle_405(_exc):
        return jsonify({"error": {"code": "method_not_allowed", "message": "متد مجاز نیست"}}), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        logger.exception("unhandled error: %s", exc)
        return (
            jsonify({"error": {"code": "internal_error", "message": "خطای داخلی سرور"}}),
            500,
        )

    @app.teardown_appcontext
    def _close(_exc):  # pragma: no cover - lifecycle hook
        return None

    # ---- CLI: outbox worker -----------------------------------------------
    import click

    @app.cli.command("outbox-worker-run-once")
    @click.option(
        "--batch-size", default=50, show_default=True, help="Maximum events to claim per run"
    )
    @click.option(
        "--lease-timeout-s",
        default=300,
        show_default=True,
        help="Seconds before a processing event is considered stale",
    )
    def outbox_worker_run_once(batch_size: int, lease_timeout_s: int):  # pragma: no cover
        """Process one batch of pending outbox events then exit.

        Safe to call from multiple concurrent processes.
        """
        from app.services.outbox_worker import run_once

        result = run_once(batch_size=batch_size, lease_timeout_s=lease_timeout_s)
        click.echo(
            f"recovered={result['recovered']} claimed={result['claimed']} "
            f"delivered={result['delivered']} failed={result['failed']} "
            f"dead_lettered={result['dead_lettered']}"
        )

    return app


def main() -> None:  # pragma: no cover - entrypoint
    import os

    app = create_app()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":  # pragma: no cover
    main()
