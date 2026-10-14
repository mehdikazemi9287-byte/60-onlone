"""Authenticated read-only configuration readiness, not a payment API."""
from flask import Blueprint, jsonify
from app.core.deps import current_user, get_db, require_auth
from app.services.organization_finance_policy import readiness

bp = Blueprint('organization_finance_policy', __name__, url_prefix='/api/v1/organizations')

@bp.get('/<int:org_id>/payment-policy')
@require_auth()
def get_readiness(org_id):
    with get_db().read_transaction() as conn:
        policy = readiness(conn, org_id, current_user()['id'])
    return jsonify({'policy': policy})
