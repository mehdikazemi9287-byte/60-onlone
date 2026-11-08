"""Read-only business dashboard. Counts use canonical records, never browser page lengths."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import Blueprint, jsonify, request
from app.core.deps import current_user, get_db, get_settings, require_auth
from app.core.errors import ValidationError
from app.services import organization_operations_service as ops

bp = Blueprint('admin_dashboard', __name__, url_prefix='/api/v1/admin')

def day_bounds(zone, now=None):
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValidationError('منطقه زمانی نامعتبر است')
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(tz)
    start = datetime.combine(local.date(), time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)

def snapshot(conn, actor_id, zone='UTC', now=None):
    now = now or datetime.now(timezone.utc)
    start, end = day_bounds(zone, now)
    count = lambda sql, args=(): int(conn.execute(sql, args).fetchone()[0])
    real_pr = 'FROM purchase_requests p JOIN organizations o ON o.id=p.organization_id WHERE o.provenance=\'real\''
    stats = {
        'personal_today': count('SELECT COUNT(*) FROM customer_requests WHERE organization_id IS NULL AND datetime(created_at)>=datetime(?) AND datetime(created_at)<datetime(?)', (start.isoformat(), end.isoformat())),
        'org_waiting': count('SELECT COUNT(*) '+real_pr+" AND p.status IN ('submitted','under_review')"),
        'quotes_submitted': count("SELECT COUNT(*) FROM supplier_quotes q JOIN rfqs r ON r.id=q.rfq_id JOIN organizations o ON o.id=r.organization_id JOIN suppliers s ON s.id=q.supplier_id WHERE o.provenance='real' AND s.provenance='real' AND q.status='submitted'"),
        'missing_images': count("SELECT COUNT(*) FROM master_products WHERE provenance='real' AND status='active' AND NOT EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(image_urls_json) THEN CASE WHEN json_type(image_urls_json)='array' THEN image_urls_json ELSE '[]' END ELSE '[]' END) j WHERE j.type='text' AND (j.value LIKE 'https://%' OR (j.value LIKE '/%' AND j.value NOT LIKE '//%')))"),
        'suppliers_inactive': count("SELECT COUNT(*) FROM suppliers WHERE provenance='real' AND status!='active'"),
        'settlements_pending': count("SELECT COUNT(*) FROM settlement_batches b JOIN suppliers s ON s.id=b.supplier_id WHERE s.provenance='real' AND b.status='pending'"),
    }
    queries = [
        ('customer_request', '/admin/inquiries', "SELECT id,subject AS title,status,created_at FROM customer_requests WHERE organization_id IS NULL AND status IN ('open','reviewing') ORDER BY created_at,id LIMIT 8"),
        ('catalog_image', '/admin/catalog-review', "SELECT id,canonical_name_fa AS title,status,updated_at AS created_at FROM master_products WHERE provenance='real' AND status='active' AND NOT EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(image_urls_json) THEN CASE WHEN json_type(image_urls_json)='array' THEN image_urls_json ELSE '[]' END ELSE '[]' END) j WHERE j.type='text' AND (j.value LIKE 'https://%' OR (j.value LIKE '/%' AND j.value NOT LIKE '//%'))) ORDER BY id LIMIT 8"),
        ('supplier', '/admin/suppliers', "SELECT id,display_name AS title,status,updated_at AS created_at FROM suppliers WHERE provenance='real' AND status!='active' ORDER BY id LIMIT 8"),
    ]
    queue=[]
    for kind, href, sql in queries:
        queue.extend({**dict(r), 'kind':kind, 'href':href} for r in conn.execute(sql))
    scoped = ops.queue(conn, actor_id)
    return {'as_of':now.isoformat(), 'timezone':zone, 'range_start':start.isoformat(), 'range_end':end.isoformat(),
            'metrics':stats, 'attention':queue, 'attention_is_sample':True,
            'operations':{'scope_count':len(scoped['scopes']), 'items':scoped['items'][:8], 'has_more':len(scoped['items'])>8},
            'integrations':{'sepidar':'not_connected'}}

@bp.get('/dashboard')
@require_auth('admin')
def dashboard():
    with get_db().read_transaction() as conn:
        data=snapshot(conn,current_user()['id'],request.args.get('timezone','UTC'))
    data['environment']=get_settings().app_env
    return jsonify(data)
