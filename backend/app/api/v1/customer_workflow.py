from flask import Blueprint,jsonify,request
from app.core.deps import require_auth,current_user,get_db,get_settings
from app.services import customer_workflow as service
bp=Blueprint('customer_workflow',__name__,url_prefix='/api/v1/organizations')
@bp.get('/<int:org_id>/workflows')
@require_auth()
def listing(org_id):
 user=current_user()['id']
 with get_db().read_transaction() as c:
  from app.services.organization_operations_service import capabilities
  caps=capabilities(c,org_id,user)
  member=c.execute("SELECT m.role FROM organization_memberships m JOIN organizations o ON o.id=m.organization_id AND o.status='active' WHERE m.user_id=? AND m.organization_id=? AND m.status='active'",(user,org_id)).fetchone()
  if not caps and (not member or member['role'] not in ('organization_admin','organization_finance')):
   from app.core.errors import PermissionError_
   raise PermissionError_('مجوز گردش سفارش ندارید')
  rows=[]
  for row in c.execute('SELECT ca.*,pr.title,pr.request_number,w.next_action,w.due_at,w.blocked_reason,o.id AS order_id,o.status AS order_status FROM organization_operations_cases ca JOIN purchase_requests pr ON pr.id=ca.purchase_request_id AND pr.organization_id=ca.organization_id LEFT JOIN customer_workflows w ON w.case_id=ca.id LEFT JOIN customer_orders o ON o.case_id=ca.id WHERE ca.organization_id=? ORDER BY ca.id DESC',(org_id,)):
   if member and member['role'] in ('organization_admin','organization_finance') or 'case_manager'in caps or row['assignee_user_id']==user:
    entry=dict(row)
    if not caps or ('case_manager' not in caps and row['assignee_user_id']!=user):
     for field in ['next_action','due_at','blocked_reason']:entry.pop(field,None)
    rows.append(entry)
 return jsonify({'items':rows})
@bp.get('/<int:org_id>/workflows/<int:case_id>')
@require_auth()
def detail(org_id,case_id):
 with get_db().read_transaction() as c:r=service.read(c,org_id,case_id,current_user()['id'])
 r['execution_context']='TEST/SIMULATED' if get_settings().app_env=='test' else 'REAL_FINANCE_DISABLED'
 return jsonify(r)
@bp.post('/<int:org_id>/workflows/<int:case_id>/<action>')
@require_auth()
def mutate(org_id,case_id,action):
 settings=get_settings()
 with get_db().write_transaction() as c:r=service.mutate(c,org_id,case_id,current_user()['id'],action,request.get_json(silent=True),request.headers.get('Idempotency-Key'),settings.app_env,settings.currency)
 r['execution_context']='TEST/SIMULATED' if get_settings().app_env=='test' else 'REAL_FINANCE_DISABLED'
 return jsonify(r)

@bp.get('/<int:org_id>/workflow-intake')
@require_auth()
def intake(org_id):
 from app.services import organization_operations_service as ops
 from app.core.errors import PermissionError_
 with get_db().read_transaction() as c:
  if 'case_manager' not in ops.authorize(c,org_id,current_user()['id']):raise PermissionError_('مجوز مدیریت لازم است')
  rows=[dict(r) for r in c.execute("SELECT pr.id,pr.request_number,pr.title,pr.status FROM purchase_requests pr WHERE pr.organization_id=? AND pr.status IN ('submitted','approved') AND NOT EXISTS(SELECT 1 FROM organization_operations_cases ca WHERE ca.purchase_request_id=pr.id) ORDER BY pr.id DESC",(org_id,))]
  operators=[dict(r) for r in c.execute("SELECT DISTINCT u.id,u.full_name FROM users u JOIN organization_operations_grants g ON g.user_id=u.id WHERE g.organization_id=? AND g.status='active' AND u.is_active=1 ORDER BY u.full_name",(org_id,))]
 return jsonify({'requests':rows,'operators':operators})

@bp.get('/<int:org_id>/workflow-options/<int:case_id>')
@require_auth()
def options(org_id,case_id):
 with get_db().read_transaction() as c:
  _,role,staff=service.access(c,org_id,case_id,current_user()['id'])
  policies=[dict(r) for r in c.execute('SELECT id,version,contract_reference,environment FROM customer_payment_policies WHERE organization_id=? AND environment=?',(org_id,get_settings().app_env))]
  suppliers=[dict(r) for r in c.execute("SELECT id,display_name FROM suppliers WHERE status='active' ORDER BY display_name")] if staff else []
 return jsonify({'policies':policies,'suppliers':suppliers,'financial_execution':'test_only' if get_settings().app_env=='test' else 'disabled'})
