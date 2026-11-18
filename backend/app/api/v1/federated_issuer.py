"""Federated credit issuer connector (60Online-issued credit accepted by VandaPay). Flag-off interface stub.

See app/services/federated_issuer_service.py and docs/decisions/2026-11-18-federated-credit-vandapay.md.
Every route answers 404 unless FEDERATED_ISSUER_ENABLED=1 and FEDERATED_ISSUER_SECRET are set.
"""
from flask import Blueprint, jsonify, request

from app.services import federated_issuer_service as issuer

bp = Blueprint("federated_issuer", __name__, url_prefix="/api/v1/federation/issuer")


def _run(operation: str, authorization_id: str | None = None):
    status, body = issuer.handle(
        operation, raw_body=request.get_data(cache=True),
        signature_header=request.headers.get(issuer.INBOUND_SIGNATURE_HEADER),
        idempotency_key=request.headers.get("Idempotency-Key"), authorization_id=authorization_id)
    return jsonify(body), status


@bp.post("/eligibility")
def eligibility():
    return _run("eligibility")


@bp.post("/authorizations")
def authorize():
    return _run("authorize")


@bp.post("/authorizations/<authorization_id>/capture")
def capture(authorization_id: str):
    return _run("capture", authorization_id)


@bp.post("/authorizations/<authorization_id>/void")
def void(authorization_id: str):
    return _run("void", authorization_id)


@bp.post("/authorizations/<authorization_id>/refunds")
def refund(authorization_id: str):
    return _run("refund", authorization_id)
