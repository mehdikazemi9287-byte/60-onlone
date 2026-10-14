"""Read-only policy readiness, derived from the approved payment policy (payment_policy_service lifecycle).

Company policy may exist outside this system; absence here is not a legal finding.
This contract deliberately has no balances, limits, settlement or payment methods.
"""
from app.core.errors import PermissionError_

CATEGORIES = ('cash', 'cheque', 'credit', 'bill_undertaking', 'allocation',
              'maturity', 'collection', 'returns', 'settlement')
METHODS = ('cash', 'cheque', 'credit', 'bill', 'undertaking')


def readiness(conn, organization_id, user_id):
    member = conn.execute('''SELECT m.role FROM organization_memberships m
        JOIN organizations o ON o.id=m.organization_id AND o.status='active'
        JOIN users u ON u.id=m.user_id AND u.is_active=1
        WHERE m.organization_id=? AND m.user_id=? AND m.status='active'
        AND m.role IN ('organization_admin','organization_finance')''',
        (organization_id, user_id)).fetchone()
    if member is None:
        raise PermissionError_('مجوز فعال مالی این سازمان لازم است')
    policy = _effective(conn, organization_id)
    if policy:
        allowed = set(policy['methods']) | ({'undertaking'} if 'bill' in policy['methods'] else set())
        return {
            'organization_id': organization_id,
            'configuration_status': 'approved',
            'policy_version': policy['version'],
            'approved_contract_reference': policy['contract_reference'],
            'environment': policy['environment'],
            'effective_from': policy.get('effective_from'),
            'financial_actions_enabled': True,
            'methods': [{'code': code, 'enabled': code in allowed} for code in METHODS],
            'matrix': [{'code': code, 'status': 'CONFIGURED' if code not in ('cash', 'cheque', 'credit', 'bill_undertaking')
                        or code.split('_')[0] in allowed else 'NOT_IN_POLICY', 'requirements': [],
                        'enabled': code not in ('cash', 'cheque', 'credit', 'bill_undertaking') or code.split('_')[0] in allowed}
                       for code in CATEGORIES],
        }
    pending = _pending(conn, organization_id)
    return {
        'organization_id': organization_id,
        'configuration_status': 'awaiting_approval' if pending else 'not_configured',
        'pending_drafts': pending,
        'policy_version': None,
        'approved_contract_reference': None,
        'financial_actions_enabled': False,
        'methods': [{'code': code, 'enabled': False} for code in METHODS],
        'matrix': [{'code': code, 'status': 'TECHNICAL_GAP',
                    'requirements': ['POLICY_REQUIRED'] + (
                        ['ACCESS_REQUIRED'] if code in ('cash', 'settlement') else []),
                    'enabled': False} for code in CATEGORIES],
    }


def _has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (name,)).fetchone() is not None


def _effective(conn, organization_id):
    """The approved policy procurement finance enforces today (same rule as procurement_finance_service)."""
    if not _has_table(conn, 'customer_payment_policies') or not _has_table(conn, 'payment_policy_drafts'):
        return None
    from app.services.procurement_finance_service import policy
    return policy(conn, organization_id)


def _pending(conn, organization_id):
    if not _has_table(conn, 'payment_policy_drafts'):
        return 0
    return conn.execute("SELECT COUNT(*) FROM payment_policy_drafts WHERE organization_id=? AND status IN ('draft','in_review')",
                        (organization_id,)).fetchone()[0]
