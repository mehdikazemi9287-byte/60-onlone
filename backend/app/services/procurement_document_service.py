"""Delivery evidence and order documents for purchase orders.

Uploads are validated by magic bytes (PDF/JPEG/PNG/WebP), capped at 5 MB, stored content-addressed
under <database dir>/documents, and recorded append-only. Access: the PO's supplier (owner/operator),
members of the PO's organization, and platform admins.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.core.errors import NotFoundError, PermissionError_, ValidationError
from app.services import procurement_service as pr_svc

MAX_BYTES = 5 * 1024 * 1024
KINDS = ("delivery_evidence", "waybill", "supplier_invoice", "other")
KIND_FA = {"delivery_evidence": "مدرک تحویل", "waybill": "بارنامه", "supplier_invoice": "صورت‌حساب تأمین‌کننده", "other": "سایر"}
_MAGIC = [(b"%PDF-", "application/pdf", "pdf"), (b"\xff\xd8\xff", "image/jpeg", "jpg"),
          (b"\x89PNG\r\n\x1a\n", "image/png", "png")]


def storage_dir() -> Path:
    from app.core.deps import get_settings
    url = get_settings().database_url
    base = Path(url.replace("sqlite:///", "", 1)).parent if url.startswith("sqlite:///") else Path("/tmp")
    d = Path(os.environ.get("DOCUMENT_STORAGE_DIR") or base / "documents")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sniff(data: bytes) -> tuple[str, str]:
    for magic, ctype, ext in _MAGIC:
        if data.startswith(magic):
            return ctype, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    raise ValidationError("فقط فایل PDF، JPEG، PNG یا WebP مجاز است")


def save(conn, *, po, actor: int, side: str, data: bytes, filename: str, kind: str, destination_index, note) -> dict:
    if kind not in KINDS:
        raise ValidationError("نوع سند نامعتبر است")
    if not data or len(data) > MAX_BYTES:
        raise ValidationError("حجم فایل باید بین ۱ بایت و ۵ مگابایت باشد")
    ctype, ext = _sniff(data)
    if destination_index is not None:
        try:
            destination_index = int(destination_index)
        except (TypeError, ValueError):
            raise ValidationError("مقصد نامعتبر است")
    digest = hashlib.sha256(data).hexdigest()
    path = storage_dir() / f"{digest}.{ext}"
    if not path.exists():
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    name = os.path.basename(filename or f"document.{ext}")[:120]
    doc_id = conn.execute(
        """INSERT INTO procurement_documents (purchase_order_id, destination_index, kind, filename, content_type, size_bytes, sha256,
               note, uploaded_by_user_id, uploader_side) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (po["id"], destination_index, kind, name, ctype, len(data), digest, (note or "")[:500] or None, actor, side)).lastrowid
    return get(conn, doc_id)


def get(conn, doc_id: int) -> dict:
    r = conn.execute("""SELECT d.*, u.full_name AS uploader FROM procurement_documents d JOIN users u ON u.id=d.uploaded_by_user_id
                        WHERE d.id=?""", (doc_id,)).fetchone()
    if not r:
        raise NotFoundError("سند یافت نشد")
    return dict(r) | {"kind_fa": KIND_FA[r["kind"]], "url": f"/api/v1/procurement-documents/{r['id']}"}


def list_for_po(conn, po_id: int) -> list[dict]:
    return [get(conn, r[0]) for r in conn.execute("SELECT id FROM procurement_documents WHERE purchase_order_id=? ORDER BY id", (po_id,))]


def authorize_read(conn, doc: dict, user: dict) -> None:
    if user["role"] == "admin":
        return
    po = conn.execute("""SELECT o.organization_id, q.supplier_id FROM purchase_orders o
                         LEFT JOIN supplier_quotes q ON q.id=o.awarded_supplier_quote_id WHERE o.id=?""", (doc["purchase_order_id"],)).fetchone()
    if po and conn.execute("SELECT 1 FROM supplier_access WHERE user_id=? AND supplier_id=?", (user["id"], po["supplier_id"])).fetchone():
        return
    if po and conn.execute("SELECT 1 FROM organization_memberships WHERE user_id=? AND organization_id=? AND status='active'",
                           (user["id"], po["organization_id"])).fetchone():
        return
    raise NotFoundError("سند یافت نشد")


def file_path(doc: dict) -> Path:
    ext = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[doc["content_type"]]
    return storage_dir() / f"{doc['sha256']}.{ext}"


def buyer_can_upload(conn, org: int, actor: int) -> None:
    m = pr_svc._assert_org_member(conn, actor, org)
    if not (pr_svc._can_procure(m) or m["role"] == "organization_admin" or m.get("procurement_role") == "requester"):
        raise PermissionError_("بارگذاری سند برای نقش تدارکات، مدیر یا درخواست‌دهنده مجاز است")
