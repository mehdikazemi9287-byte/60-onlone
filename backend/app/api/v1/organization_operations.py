"""Authenticated internal case API; no grant provisioning endpoint."""
from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.core.errors import ValidationError
from app.services import organization_operations_service as service

bp = Blueprint('organization_operations', __name__, url_prefix='/api/v1/internal/organizations')


@bp.get('')
@require_auth()
def my_internal_organizations():
    with get_db().read_transaction() as conn:
        items = service.list_scopes(conn, current_user()['id'])
    return jsonify({'items': items})


@bp.get('/<int:org_id>/cases')
@require_auth()
def list_cases(org_id):
    try:
        after = int(request.args.get('after', '0'))
        limit = int(request.args.get('limit', '50'))
    except ValueError:
        raise ValidationError('صفحه‌بندی نامعتبر است')
    with get_db().read_transaction() as conn:
        result = service.list_cases(conn, org_id, current_user()['id'], after, limit)
    return jsonify(result)


@bp.get('/<int:org_id>/cases/<int:case_id>')
@require_auth()
def get_case(org_id, case_id):
    with get_db().read_transaction() as conn:
        result = service.get_case(conn, org_id, case_id, current_user()['id'])
    return jsonify({'case': result})


def _mutate(org_id, action, case_id=None):
    with get_db().write_transaction() as conn:
        result = service.mutate(conn, org_id, current_user()['id'], action,
                                request.get_json(silent=True),
                                request.headers.get('Idempotency-Key'), case_id)
    return jsonify(result), 200


@bp.post('/<int:org_id>/cases')
@require_auth()
def create_case(org_id):
    return _mutate(org_id, 'create')


@bp.post('/<int:org_id>/cases/<int:case_id>/assign')
@require_auth()
def assign_case(org_id, case_id):
    return _mutate(org_id, 'assign', case_id)


@bp.post('/<int:org_id>/cases/<int:case_id>/transition')
@require_auth()
def transition_case(org_id, case_id):
    return _mutate(org_id, 'transition', case_id)
