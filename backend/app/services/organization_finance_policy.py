"""Read-only policy readiness. No approved policy repository or financial activation.

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
    return {
        'organization_id': organization_id,
        'configuration_status': 'technical_policy_configuration_unavailable',
        'policy_version': None,
        'approved_contract_reference': None,
        'financial_actions_enabled': False,
        'methods': [{'code': code, 'enabled': False} for code in METHODS],
        'matrix': [{'code': code, 'status': 'TECHNICAL_GAP',
                    'requirements': ['POLICY_REQUIRED'] + (
                        ['ACCESS_REQUIRED'] if code in ('cash', 'settlement') else []),
                    'enabled': False} for code in CATEGORIES],
    }
