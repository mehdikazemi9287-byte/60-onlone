"""Internal case coordination only: never changes procurement or financial state.

Staff mandates are independent of customer memberships and platform roles.
Managers can inspect/reassign revoked cases; agents can only access their own
cases while their explicit scoped mandate remains active.
"""
from __future__ import annotations

import hashlib
import json

from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError

TRANSITIONS = {
    'unassigned': set(),
    'triage': {'sourcing', 'waiting_customer', 'blocked', 'closed'},
    'sourcing': {'waiting_customer', 'blocked', 'closed'},
    'waiting_customer': {'triage', 'sourcing', 'blocked', 'closed'},
    'blocked': {'triage', 'sourcing', 'waiting_customer', 'closed'},
    'closed': set(),
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _positive(value, field):
    if type(value) is not int or value < 1:
        raise ValidationError(f'{field} باید عدد صحیح مثبت باشد')
    return value


def capabilities(conn, org_id, user_id):
    rows = conn.execute(
        """SELECT g.capability FROM organization_operations_grants g
           JOIN organizations o ON o.id=g.organization_id AND o.status='active'
           JOIN users u ON u.id=g.user_id AND u.is_active=1
           WHERE g.organization_id=? AND g.user_id=? AND g.status='active'""",
        (org_id, user_id),
    ).fetchall()
    return {r['capability'] for r in rows}


def list_scopes(conn, user_id):
    """Discover only actual internal mandates; customer memberships imply none."""
    rows = conn.execute(
        """SELECT o.id,o.display_name,g.capability
           FROM organization_operations_grants g
           JOIN organizations o ON o.id=g.organization_id AND o.status='active'
           JOIN users u ON u.id=g.user_id AND u.is_active=1
           WHERE g.user_id=? AND g.status='active' ORDER BY o.id,g.capability""",
        (user_id,),
    ).fetchall()
    scopes = {}
    for row in rows:
        scope = scopes.setdefault(row['id'], {
            'id': row['id'], 'display_name': row['display_name'], 'capabilities': []})
        scope['capabilities'].append(row['capability'])
    return list(scopes.values())


def authorize(conn, org_id, user_id):
    caps = capabilities(conn, org_id, user_id)
    if not caps:
        raise PermissionError_('مجوز فعال عملیات داخلی این سازمان لازم است')
    return caps


def _case(conn, org_id, case_id, user_id, caps):
    row = conn.execute(
        'SELECT * FROM organization_operations_cases WHERE id=? AND organization_id=?',
        (case_id, org_id),
    ).fetchone()
    if not row:
        raise NotFoundError('پرونده یافت نشد')
    if 'case_manager' not in caps and row['assignee_user_id'] != user_id:
        raise PermissionError_('پرونده به شما واگذار نشده است')
    return dict(row)


def get_case(conn, org_id, case_id, user_id):
    caps = authorize(conn, org_id, user_id)
    case = _case(conn, org_id, case_id, user_id, caps)
    # Re-check the linked organization's identity; never trust a case FK alone.
    request = conn.execute(
        """SELECT id,request_number,title,status,needed_by_date,substitution_policy,
                  destinations_json FROM purchase_requests
           WHERE id=? AND organization_id=?""",
        (case['purchase_request_id'], org_id),
    ).fetchone()
    if not request:
        raise NotFoundError('درخواست مرتبط با این سازمان یافت نشد')
    context = dict(request)
    context['destinations'] = json.loads(context.pop('destinations_json'))
    context['items'] = [dict(r) for r in conn.execute(
        """SELECT id,master_product_id,free_text_description,quantity,unit,notes
           FROM purchase_request_items WHERE purchase_request_id=? ORDER BY id""",
        (request['id'],),
    ).fetchall()]
    case['purchase_request'] = context
    case['capabilities'] = sorted(caps)
    case['events'] = [dict(r) for r in conn.execute(
        'SELECT * FROM organization_operations_events WHERE case_id=? ORDER BY id',
        (case_id,),
    ).fetchall()]
    return case


def list_cases(conn, org_id, user_id, after=0, limit=50):
    caps = authorize(conn, org_id, user_id)
    if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValidationError('صفحه‌بندی نامعتبر است')
    sql = 'SELECT * FROM organization_operations_cases WHERE organization_id=? AND id>?'
    params = [org_id, after]
    if 'case_manager' not in caps:
        sql += ' AND assignee_user_id=?'
        params.append(user_id)
    rows = conn.execute(sql + ' ORDER BY id LIMIT ?', (*params, limit + 1)).fetchall()
    items = [dict(r) for r in rows[:limit]]
    return {'items': items, 'next_cursor': items[-1]['id'] if len(rows) > limit else None}


def mutate(conn, org_id, user_id, action, data, key, case_id=None):
    """Caller must supply one write transaction for authorization + all changes."""
    caps = authorize(conn, org_id, user_id)
    if action in {'create', 'assign'} and 'case_manager' not in caps:
        raise PermissionError_('مجوز مدیریت پرونده لازم است')
    before = _case(conn, org_id, case_id, user_id, caps) if case_id is not None else None
    if not isinstance(data, dict):
        raise ValidationError('بدنه درخواست باید شیء باشد')
    allowed = {
        'create': {'purchase_request_id', 'reason'},
        'assign': {'assignee_user_id', 'expected_version', 'reason'},
        'transition': {'status', 'expected_version', 'reason'},
    }
    if action not in allowed or set(data) != allowed[action]:
        raise ValidationError('فیلدهای درخواست نامعتبر است')
    reason = data['reason']
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        raise ValidationError('دلیل باید بین ۱ تا ۱۰۰۰ نویسه باشد')
    if not isinstance(key, str) or not 1 <= len(key.strip()) <= 128 or len(key) > 128:
        raise ValidationError('Idempotency-Key الزامی و حداکثر ۱۲۸ نویسه است')
    digest = hashlib.sha256(_json([action, case_id, data]).encode()).hexdigest()
    old = conn.execute(
        'SELECT * FROM organization_operations_idempotency WHERE organization_id=? AND actor_user_id=? AND key=?',
        (org_id, user_id, key),
    ).fetchone()
    if old:
        if old['payload_hash'] != digest:
            raise ConflictError('شناسه درخواست قبلاً با داده متفاوت استفاده شده است', code='idempotency_conflict')
        _case(conn, org_id, old['case_id'], user_id, caps)
        return json.loads(old['response_json'])
    if action == 'create':
        pr_id = _positive(data['purchase_request_id'], 'purchase_request_id')
        pr = conn.execute('SELECT id FROM purchase_requests WHERE id=? AND organization_id=?', (pr_id, org_id)).fetchone()
        if not pr:
            raise NotFoundError('درخواست خرید این سازمان یافت نشد')
        if conn.execute('SELECT id FROM organization_operations_cases WHERE purchase_request_id=?', (pr_id,)).fetchone():
            raise ConflictError('پرونده درخواست قبلاً ایجاد شده است')
        cursor = conn.execute(
            'INSERT INTO organization_operations_cases(organization_id,purchase_request_id) VALUES (?,?)',
            (org_id, pr_id),
        )
        case_id = cursor.lastrowid
    else:
        version = _positive(data['expected_version'], 'expected_version')
        if before['version'] != version:
            raise ConflictError('نسخه پرونده تغییر کرده است', code='stale_version')
        if before['status'] == 'closed':
            raise ConflictError('پرونده بسته شده است')
        if action == 'assign':
            assignee = _positive(data['assignee_user_id'], 'assignee_user_id')
            if not capabilities(conn, org_id, assignee):
                raise ValidationError('مسئول باید مجوز فعال عملیات همین سازمان را داشته باشد')
            status = 'triage' if before['status'] == 'unassigned' else before['status']
        else:
            assignee = before['assignee_user_id']
            if not assignee or not capabilities(conn, org_id, assignee):
                raise ConflictError('مسئول فعال لازم است؛ مدیر باید پرونده را دوباره واگذار کند')
            status = data['status']
            if not isinstance(status, str) or status not in TRANSITIONS[before['status']]:
                raise ConflictError('تغییر وضعیت مجاز نیست')
        if status == 'closed':
            commercial = conn.execute('SELECT status FROM customer_orders WHERE case_id=?',(case_id,)).fetchone()
            if commercial and commercial['status'] not in ('closed','cancelled'):
                raise ConflictError('سفارش مشتری باز است؛ ابتدا گردش سفارش را تکمیل کنید')
        changed = conn.execute(
            """UPDATE organization_operations_cases SET assignee_user_id=?,status=?,version=version+1,
               updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND version=?""",
            (assignee, status, case_id, version),
        )
        if changed.rowcount != 1:
            raise ConflictError('نسخه پرونده تغییر کرده است', code='stale_version')
    after = dict(conn.execute('SELECT * FROM organization_operations_cases WHERE id=?', (case_id,)).fetchone())
    conn.execute(
        'INSERT INTO organization_operations_events(case_id,actor_user_id,action,reason,before_json,after_json) VALUES (?,?,?,?,?,?)',
        (case_id, user_id, action, reason.strip(), _json(before), _json(after)),
    )
    response = {'case': after}
    conn.execute(
        'INSERT INTO organization_operations_idempotency(organization_id,actor_user_id,key,payload_hash,case_id,response_json) VALUES (?,?,?,?,?,?)',
        (org_id, user_id, key, digest, case_id, _json(response)),
    )
    return response


def queue(conn, user_id, *, org=None, q=None, stage=None, ops_status=None, assignee=None):
    """Cross-organization work queue for operations staff.

    Commercial state comes from the authoritative procurement records (enterprise list_cases);
    only ownership / coordination status comes from organization_operations_cases.
    """
    from app.services import enterprise_procurement_service as ent
    scopes = list_scopes(conn, user_id)
    if org is not None:
        scopes = [s for s in scopes if s['id'] == org]
        if not scopes:
            raise PermissionError_('مجوز فعال عملیات داخلی این سازمان لازم است')
    items, staff = [], {}
    for scope in scopes:
        caps = set(scope['capabilities'])
        cases = {r['purchase_request_id']: dict(r) for r in conn.execute(
            """SELECT c.*, u.full_name AS assignee FROM organization_operations_cases c
               LEFT JOIN users u ON u.id=c.assignee_user_id WHERE c.organization_id=?""", (scope['id'],))}
        staff[scope['id']] = [dict(r) for r in conn.execute(
            """SELECT DISTINCT u.id, u.full_name, g.capability FROM organization_operations_grants g
               JOIN users u ON u.id=g.user_id AND u.is_active=1
               WHERE g.organization_id=? AND g.status='active' ORDER BY u.full_name""", (scope['id'],))]
        for row in ent.list_cases(conn, organization_id=scope['id'], actor_user_id=user_id, q=q, stage=stage,
                                  platform=True)['items']:
            case = cases.get(row['id'])
            if 'case_manager' not in caps and (not case or case['assignee_user_id'] != user_id):
                continue
            status = case['status'] if case else 'none'
            if ops_status and status != ops_status:
                continue
            if assignee == 'me' and (not case or case['assignee_user_id'] != user_id):
                continue
            if assignee == 'none' and case and case['assignee_user_id']:
                continue
            row['operations'] = {'case_id': case['id'] if case else None, 'status': status,
                                 'assignee_user_id': case['assignee_user_id'] if case else None,
                                 'assignee': case['assignee'] if case else None,
                                 'version': case['version'] if case else None,
                                 'updated_at': case['updated_at'] if case else None}
            row['capabilities'] = sorted(caps)
            items.append(row)
    return {'items': items, 'scopes': scopes, 'staff': staff}
