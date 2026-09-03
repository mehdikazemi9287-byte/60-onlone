"""Connector adapter registry — Phase 7 Universal Integration Gateway.

Maps connector_type strings (stored in connector_accounts.connector_type) to
adapter classes. Returns a ConnectorAdapter instance ready to use.

CONNECTOR CONTRACT VERSION: 2.0

REAL PROVIDER INTEGRATIONS — NOT IMPLEMENTED:
  Holo, Sepidar, Rahkaran, SAP, Odoo, AloPeyk, Post, Tipax, Chapar,
  GS1 lookup, and Moadian adapters are registered as clearly-marked
  NOT IMPLEMENTED stubs. No endpoints are fabricated.

SECURITY:
  - credential_ref is passed through but NEVER logged or stored plaintext.
  - Adapters run in caller's thread; no secrets are shared across tenants.
"""
from __future__ import annotations

from app.adapters.connectors.base import (
    CAPABILITY_HEALTH_CHECK,
    CAPABILITY_PULL_INVENTORY,
    CAPABILITY_PULL_PRICES,
    CAPABILITY_PULL_PRODUCTS,
    CAPABILITY_PUSH_ORDERS,
    CAPABILITY_RESOLVE_PRODUCT,
    CapabilityDeclaration,
    ConnectorAdapter,
    ConnectorError,
    ConnectorErrorCode,
    SyncCursor,
    WebhookVerificationResult,
)
from app.adapters.connectors.csv_connector import CsvConnector
from app.adapters.connectors.mock_erp import MockErpConnector
from app.adapters.connectors.mock_erp_v2 import MockErpV2Connector
from app.core.errors import ValidationError


# ─────────────────────────────────────────────────────────────────────────────
# Not-yet-implemented stub
# ─────────────────────────────────────────────────────────────────────────────

class _NotYetImplementedAdapter(ConnectorAdapter):
    """Clearly-marked stub for connectors that are not yet implemented.

    PRODUCTION READINESS: NOT IMPLEMENTED
    No vendor API calls are made. No endpoints are fabricated.
    """

    def __init__(self, connector_type: str, docs_url: str = "", notes: str = ""):
        self.adapter_name = connector_type
        self._docs_url = docs_url
        self._notes = notes

    def capabilities(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            connector_type=self.adapter_name,
            adapter_name=self.adapter_name,
            supported=[],
            implementation_status="not_implemented",
            verified_docs_url=self._docs_url or None,
            notes=self._notes or f"{self.adapter_name}: REAL PROVIDER — NOT IMPLEMENTED",
        )

    def health_check(self) -> dict:
        return {
            "healthy": False,
            "message": (
                f"اتصال '{self.adapter_name}' هنوز پیاده‌سازی نشده. "
                "REAL PROVIDER: NOT IMPLEMENTED. "
                + (f"مستندات: {self._docs_url}" if self._docs_url else "مستندات رسمی تأیید نشده.")
            ),
            "latency_ms": None,
        }

    def pull_products(self, *, limit=100, offset=0, cursor=None, **_):
        raise ConnectorError(
            f"اتصال '{self.adapter_name}' پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    def pull_prices(self, *, product_codes=None, limit=500, offset=0, cursor=None, **_):
        raise ConnectorError(
            f"اتصال '{self.adapter_name}' پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    def pull_inventory(self, *, product_codes=None, limit=500, offset=0, cursor=None, **_):
        raise ConnectorError(
            f"اتصال '{self.adapter_name}' پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    def push_order(self, order_data: dict) -> dict:
        raise ConnectorError(
            f"اتصال '{self.adapter_name}' پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    def resolve_product(self, *, identifier_type: str, identifier_value: str):
        raise ConnectorError(
            f"اتصال '{self.adapter_name}' پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Manual adapter
# ─────────────────────────────────────────────────────────────────────────────

class _ManualAdapter(ConnectorAdapter):
    """Manual/static connector — always healthy, returns empty data."""

    adapter_name = "MANUAL"

    def capabilities(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            connector_type="MANUAL",
            adapter_name="MANUAL",
            supported=[CAPABILITY_HEALTH_CHECK, CAPABILITY_PUSH_ORDERS],
            transport="PULL",
            implementation_status="production",
            notes="Manual entry — no external sync required",
        )

    def health_check(self) -> dict:
        return {
            "healthy": True,
            "message": "اتصال دستی — نیاز به همگام‌سازی ندارد",
            "latency_ms": 0,
        }

    def pull_products(self, *, limit=100, offset=0, cursor=None, **_):
        return [], None

    def pull_prices(self, *, product_codes=None, limit=500, offset=0, cursor=None, **_):
        return [], None

    def pull_inventory(self, *, product_codes=None, limit=500, offset=0, cursor=None, **_):
        return [], None

    def push_order(self, order_data: dict) -> dict:
        return {"acknowledged": True, "external_ref": None, "message": "دستی — نیاز به push ندارد"}

    def resolve_product(self, *, identifier_type: str, identifier_value: str):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Not-yet-implemented registry entries with documentation references
# ─────────────────────────────────────────────────────────────────────────────

# IMPORTANT: Only official, verified documentation URLs are listed here.
# If official docs are unavailable, the entry is left blank.
# No endpoints are fabricated. No mock APIs for real vendors.

_NOT_IMPLEMENTED_REGISTRY: dict[str, dict] = {
    "HOLO_ERP": {
        "docs_url": "",  # Official Holo ERP API docs not publicly available
        "notes": "هلو ERP — REAL PROVIDER: NOT IMPLEMENTED. مستندات رسمی API در دسترس عموم نیست.",
    },
    "SEPIDAR_ERP": {
        "docs_url": "",  # Official Sepidar API docs require vendor agreement
        "notes": "سپیدار ERP — REAL PROVIDER: NOT IMPLEMENTED. مستندات رسمی API نیاز به قرارداد فروشنده دارد.",
    },
    "RAHKARAN_ERP": {
        "docs_url": "",  # Rahkaran/Hamkaran API docs not publicly available
        "notes": "راهکاران ERP — REAL PROVIDER: NOT IMPLEMENTED. مستندات رسمی API در دسترس عموم نیست.",
    },
    "SAP_ERP": {
        "docs_url": "https://api.sap.com/",
        "notes": "SAP ERP — REAL PROVIDER: NOT IMPLEMENTED. SAP Business One API documented at api.sap.com.",
    },
    "ODOO_ERP": {
        "docs_url": "https://www.odoo.com/documentation/17.0/developer/reference/external_api.html",
        "notes": "Odoo ERP — REAL PROVIDER: NOT IMPLEMENTED. XML-RPC/JSON-RPC API documented; requires Odoo instance credentials.",
    },
    "REST_API": {
        "docs_url": "",
        "notes": "Generic REST API connector — REAL PROVIDER: NOT IMPLEMENTED. Configure endpoint in config_json.",
    },
    "WEBHOOK": {
        "docs_url": "",
        "notes": "Webhook receiver — REAL PROVIDER: NOT IMPLEMENTED. Endpoint and signature method vendor-specific.",
    },
    "SFTP": {
        "docs_url": "",
        "notes": "SFTP file feed — REAL PROVIDER: NOT IMPLEMENTED.",
    },
    "FTP": {
        "docs_url": "",
        "notes": "FTP file feed — REAL PROVIDER: NOT IMPLEMENTED.",
    },
    "XLSX_IMPORT": {
        "docs_url": "",
        "notes": "Excel XLSX import — REAL PROVIDER: NOT IMPLEMENTED. Use CSV_IMPORT for file-based import.",
    },
    "ALOPEYK": {
        "docs_url": "",  # AloPeyk API docs require partner agreement
        "notes": "AloPeyk logistics — REAL PROVIDER: NOT IMPLEMENTED. مستندات API نیاز به قرارداد شریک دارد.",
    },
    "POST_IR": {
        "docs_url": "",  # Iran Post API not publicly documented
        "notes": "Iran Post (پست ایران) — REAL PROVIDER: NOT IMPLEMENTED. مستندات API رسمی در دسترس عموم نیست.",
    },
    "TIPAX": {
        "docs_url": "",  # Tipax API not publicly documented
        "notes": "Tipax — REAL PROVIDER: NOT IMPLEMENTED. مستندات API رسمی در دسترس عموم نیست.",
    },
    "CHAPAR": {
        "docs_url": "",  # Chapar API not publicly documented
        "notes": "Chapar — REAL PROVIDER: NOT IMPLEMENTED. مستندات API رسمی در دسترس عموم نیست.",
    },
    "SUPPLIER_FLEET": {
        "docs_url": "",
        "notes": "Supplier-owned delivery fleet — REAL PROVIDER: NOT IMPLEMENTED. Requires supplier-specific integration.",
    },
    "ACCOUNTING_CSV": {
        "docs_url": "",
        "notes": "Accounting CSV export/import — use accounting_connector_accounts table.",
    },
    "ACCOUNTING_API": {
        "docs_url": "",
        "notes": "Generic accounting API — REAL PROVIDER: NOT IMPLEMENTED.",
    },
    "SUPPLIER_FEED": {
        "docs_url": "",
        "notes": "Supplier product feed — configure feed URL in config_json.",
    },
    "MANUFACTURER_FEED": {
        "docs_url": "",
        "notes": "Manufacturer product feed — configure feed URL in config_json.",
    },
    "GS1_LOOKUP": {
        "docs_url": "https://www.gs1.org/services/verified-by-gs1",
        "notes": "GS1 GTIN lookup — REAL PROVIDER: NOT IMPLEMENTED. Requires GS1 member account and API key.",
    },
    "CUSTOM_ERP": {
        "docs_url": "",
        "notes": "Custom ERP integration — REAL PROVIDER: NOT IMPLEMENTED.",
    },
    "OTHER": {
        "docs_url": "",
        "notes": "Other connector type — REAL PROVIDER: NOT IMPLEMENTED.",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_adapter(connector_type: str, *, config: dict | None = None) -> ConnectorAdapter:
    """Return a ConnectorAdapter for the given connector_type.

    Raises ValidationError for unknown connector types.
    """
    ct = connector_type.upper()
    config = config or {}

    if ct == "MANUAL":
        return _ManualAdapter()

    if ct in ("MOCK_ERP", "MOCK_ERP_V2"):
        dataset = config.get("mock_erp_dataset", config.get("dataset", "products"))
        if ct == "MOCK_ERP_V2" or dataset == "large":
            return MockErpV2Connector(config=config)
        return MockErpConnector(dataset=dataset)

    if ct == "CSV_IMPORT":
        return CsvConnector(config=config)

    if ct in _NOT_IMPLEMENTED_REGISTRY:
        entry = _NOT_IMPLEMENTED_REGISTRY[ct]
        return _NotYetImplementedAdapter(
            ct,
            docs_url=entry.get("docs_url", ""),
            notes=entry.get("notes", ""),
        )

    raise ValidationError(f"نوع اتصال '{connector_type}' ناشناخته است")


def list_connector_types() -> list[dict]:
    """Return all supported connector types with implementation status."""
    result = [
        {
            "type": "MANUAL",
            "label": "دستی",
            "implemented": True,
            "implementation_status": "production",
            "transport": "PULL",
            "description": "ورود اطلاعات دستی — بدون اتصال خارجی",
            "verified_docs_url": None,
        },
        {
            "type": "MOCK_ERP",
            "label": "ERP آزمایشی",
            "implemented": True,
            "implementation_status": "simulator",
            "transport": "PULL",
            "description": "ERP آزمایشی — داده‌های شبیه‌سازی‌شده، بدون API واقعی",
            "verified_docs_url": None,
        },
        {
            "type": "CSV_IMPORT",
            "label": "وارد کردن CSV",
            "implemented": True,
            "implementation_status": "simulator",
            "transport": "FILE",
            "description": "وارد کردن فایل CSV — محصول، قیمت یا موجودی",
            "verified_docs_url": None,
        },
    ]
    for ct, entry in _NOT_IMPLEMENTED_REGISTRY.items():
        result.append({
            "type": ct,
            "label": ct.replace("_", " ").title(),
            "implemented": False,
            "implementation_status": "not_implemented",
            "transport": "PULL",
            "description": entry.get("notes", ""),
            "verified_docs_url": entry.get("docs_url") or None,
        })
    return result


def reset_for_tests() -> None:
    """No-op — kept for test harness compatibility with Phase 6 registry interface."""
    pass
