"""Journey E: admin/finance & regulator view via API."""
import datetime, sys
sys.path.insert(0, "/tmp/e2e")
from common import *

c = db()
s, r = api("GET", "/legal/terms")
docs = r.get("documents", []) if s == 200 else []
step("legal terms endpoint", s == 200 and any(d.get("doc_key") == "buyer_terms" for d in docs),
     f"{s} keys={[d.get('doc_key') + '@' + str(d.get('version')) for d in docs]}")

ta = c.execute("""SELECT ta.context, ta.context_ref, ta.accepted_at, ta.ip_address IS NOT NULL ip, ld.doc_key, ld.version
                  FROM terms_acceptances ta LEFT JOIN legal_documents ld ON ld.id = ta.document_id
                  WHERE ld.doc_key='buyer_terms' ORDER BY ta.id DESC LIMIT 1""").fetchone() if c.execute(
    "SELECT 1 FROM sqlite_master WHERE name='legal_documents'").fetchone() else c.execute(
    "SELECT * FROM terms_acceptances ORDER BY id DESC LIMIT 1").fetchone()
last_order = c.execute("SELECT order_number, user_id FROM orders ORDER BY id DESC LIMIT 1").fetchone()
step("terms_acceptances row after checkout", ta is not None, dict(ta) if ta else "none")
if ta is not None:
    ik = c.execute("SELECT response_json FROM idempotency_keys WHERE key=?", (ta["context_ref"],)).fetchone()
    step("acceptance traceable to order (via idempotency key)", ik and last_order["order_number"] in (ik[0] or ""),
         f"context_ref={ta['context_ref']} order={last_order['order_number']}")

ADMIN = token_for("admin@60online.ir", "Admin!2345")
sup_id = c.execute("SELECT supplier_id FROM fulfillment_orders ORDER BY id DESC LIMIT 1").fetchone()[0]
today = datetime.date.today()
period = {"period_start": today.replace(day=1).isoformat(), "period_end": today.isoformat()}
s, r = api("GET", "/admin/finance-formats", token=ADMIN)
step("admin finance formats", s == 200, str(r)[:150])
s, r = api("POST", "/admin/finance-exports", {"entity_type": "seller", "entity_id": sup_id, **period}, token=ADMIN)
step("admin creates seller finance export", s in (200, 201), f"{s} {str(r)[:160]}")
if s in (200, 201):
    jid = r["job"]["id"]
    s2, raw = api("GET", f"/admin/finance-exports/{jid}/download", token=ADMIN, raw=True)
    step("admin downloads seller export", s2 == 200 and len(raw) > 20, f"{s2} bytes={len(raw) if isinstance(raw, bytes) else raw}")

# Seller self-service export (seed supplier user linked to the order's supplier)
email = c.execute("SELECT u.email FROM supplier_users su JOIN users u ON u.id = su.user_id WHERE u.email LIKE 'seller%' ORDER BY su.supplier_id DESC LIMIT 1").fetchone()
pw = {"supplier.tehran@60online.ir": "Sup!Tehran1", "supplier.isfahan@60online.ir": "Sup!Isfahan1",
      "supplier.kermanshah@60online.ir": "Sup!Krmsh1"}.get(email[0] if email else "", "Seller!2345" if email else None)
if pw:
    tok = token_for(email[0], pw)
    s, r = api("POST", "/supplier/finance-exports", period, token=tok)
    step("seller creates own export", s in (200, 201), f"{email[0]} {s} {str(r)[:120]}")
    if s in (200, 201):
        s2, raw = api("GET", f"/supplier/finance-exports/{r['job']['id']}/download", token=tok, raw=True)
        has_order = isinstance(raw, bytes) and last_order["order_number"].encode() in raw
        step("seller downloads own export", s2 == 200 and len(raw) > 20, f"{s2} bytes={len(raw)} mentions_order={has_order}")
    s, r = api("GET", "/supplier/finance-exports", token=tok)
    step("seller lists exports", s == 200, f"jobs={len(r.get('jobs', [])) if s == 200 else r}")
else:
    step("seller creates own export", False, f"no seeded login for supplier {sup_id} ({email})")

rows = c.execute("SELECT action, entity_id, actor_user_id FROM audit_logs WHERE action LIKE 'shop_application%'").fetchall()
step("audit_logs rows for shop review", len(rows) > 0, f"{len(rows)} rows e.g. {dict(rows[0]) if rows else None}")
ev = c.execute("SELECT COUNT(*) FROM supplier_onboarding_events").fetchone()[0]
step("supplier_onboarding_events trail", ev > 0, f"{ev} rows")
wd = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%withdraw%'").fetchall()
if wd:
    n = c.execute(f"SELECT COUNT(*) FROM {wd[0][0]}").fetchone()[0]
    step(f"withdrawal persisted ({wd[0][0]})", n > 0, f"{n} rows")
summary("E")
