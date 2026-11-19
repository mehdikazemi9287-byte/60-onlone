"""Federated credit issuer connector — VandaPay Issuer Connector v1, flag-off protocol stub.

api_base registered in VandaPay: https://<host>/api/v1/federation/issuer → POST {api_base}/v1/<op>.
See app/services/federated_issuer_service.py, docs/integrations/federated-issuer-connector.md.
Every route answers 404 unless FEDERATED_ISSUER_ENABLED=1 and FEDERATED_ISSUER_SECRET are set.
"""
from flask import Blueprint, Response, request

from app.services import federated_issuer_service as issuer

bp = Blueprint("federated_issuer", __name__, url_prefix="/api/v1/federation/issuer")


@bp.post("/v1/<op>")
def issuer_op(op: str):
    if op not in issuer.OPS:
        return Response(b'{"error":{"code":"not_found"}}', status=404, mimetype="application/json")
    status, raw, headers = issuer.handle(
        op, raw_body=request.get_data(cache=True),
        signature_header=request.headers.get(issuer.INBOUND_SIGNATURE_HEADER),
        idempotency_key=request.headers.get("Idempotency-Key"),
        issuer_header=request.headers.get(issuer.ISSUER_HEADER))
    # raw bytes exactly as signed: VandaPay verifies VandaPay-Issuer-Signature over the raw response body
    return Response(raw, status=status, headers=headers)
