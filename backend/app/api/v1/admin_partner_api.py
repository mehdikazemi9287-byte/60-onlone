"""Admin management of partner API clients, keys, signing secrets and webhooks.

Secrets (API key, signing secret, webhook secret) appear in a response exactly once.
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.core.deps import client_ip, current_user, require_auth
from app.core.errors import ValidationError
from app.services import partner_api_service as svc
from app.services import partner_webhook_service as hooks

bp = Blueprint("admin_partner_api", __name__, url_prefix="/api/v1/admin/partner-clients")


def _db():
    return current_app.extensions["db"]


def _mk() -> str:
    return current_app.extensions["settings"].secret_key


def _body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("بدنه JSON نامعتبر است")
    return body


def _actor() -> int:
    return int(current_user()["id"])


@bp.after_request
def _no_store(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.get("")
@require_auth("admin")
def list_clients():
    with _db().read_transaction() as conn:
        return jsonify({"items": svc.list_clients(conn)})


@bp.post("")
@require_auth("admin")
def create_client():
    body = _body()
    with _db().write_transaction() as conn:
        client = svc.create_client(conn, data=body, actor_user_id=_actor(), ip=client_ip())
        key = svc.issue_key(conn, client_id=client["id"], actor_user_id=_actor(), ip=client_ip()) \
            if body.get("issue_key", True) else None
        client = svc.get_client(conn, client["id"])
    return jsonify({"client": client, "key": key}), 201


@bp.get("/<int:client_id>")
@require_auth("admin")
def get_client(client_id: int):
    with _db().read_transaction() as conn:
        return jsonify({"client": svc.get_client(conn, client_id),
                        "webhooks": hooks.list_subscriptions(conn, client_id),
                        "inbound": svc.list_inbound(conn, client_id=client_id, limit=20)})


@bp.patch("/<int:client_id>")
@require_auth("admin")
def update_client(client_id: int):
    body = _body()
    with _db().write_transaction() as conn:
        return jsonify({"client": svc.update_client(conn, client_id=client_id, data=body, actor_user_id=_actor(), ip=client_ip())})


@bp.post("/<int:client_id>/keys")
@require_auth("admin")
def issue_key(client_id: int):
    with _db().write_transaction() as conn:
        return jsonify({"key": svc.issue_key(conn, client_id=client_id, actor_user_id=_actor(), ip=client_ip())}), 201


@bp.post("/<int:client_id>/keys/<int:key_id>/rotate")
@require_auth("admin")
def rotate_key(client_id: int, key_id: int):
    with _db().write_transaction() as conn:
        return jsonify({"key": svc.rotate_key(conn, client_id=client_id, key_id=key_id, actor_user_id=_actor(), ip=client_ip())}), 201


@bp.post("/<int:client_id>/keys/<int:key_id>/revoke")
@require_auth("admin")
def revoke_key(client_id: int, key_id: int):
    with _db().write_transaction() as conn:
        return jsonify({"key": svc.revoke_key(conn, client_id=client_id, key_id=key_id, actor_user_id=_actor(), ip=client_ip())})


@bp.post("/<int:client_id>/signing-secret/rotate")
@require_auth("admin")
def rotate_signing(client_id: int):
    with _db().write_transaction() as conn:
        return jsonify(svc.rotate_signing_secret(conn, client_id=client_id, master_key=_mk(), actor_user_id=_actor(),
                                                 ip=client_ip())), 201


@bp.get("/<int:client_id>/inbound")
@require_auth("admin")
def inbound_log(client_id: int):
    with _db().read_transaction() as conn:
        svc.get_client(conn, client_id)
        return jsonify({"items": svc.list_inbound(conn, client_id=client_id, limit=100)})


@bp.get("/<int:client_id>/webhooks")
@require_auth("admin")
def list_webhooks(client_id: int):
    with _db().read_transaction() as conn:
        svc.get_client(conn, client_id)
        return jsonify({"items": hooks.list_subscriptions(conn, client_id), "event_types": list(hooks.EVENT_TYPES)})


@bp.post("/<int:client_id>/webhooks")
@require_auth("admin")
def create_webhook(client_id: int):
    body = _body()
    with _db().write_transaction() as conn:
        sub = hooks.create_subscription(conn, client_id=client_id, url=body.get("url"), event_types=body.get("event_types"),
                                        master_key=_mk(), actor_user_id=_actor(),
                                        allow_custom_port=body.get("allow_custom_port") is True)
        svc.audit(conn, actor_user_id=_actor(), action="partner_webhook.created", entity_type="webhook_subscription",
                  entity_id=sub["id"], metadata={"client_id": client_id, "url": sub["url"],
                                                 "allow_custom_port": sub["allow_custom_port"]}, ip=client_ip())
    return jsonify({"webhook": sub}), 201


@bp.patch("/<int:client_id>/webhooks/<int:sub_id>")
@require_auth("admin")
def update_webhook(client_id: int, sub_id: int):
    body = _body()
    with _db().write_transaction() as conn:
        sub = hooks.update_subscription(conn, client_id=client_id, sub_id=sub_id, data=body)
        svc.audit(conn, actor_user_id=_actor(), action="partner_webhook.updated", entity_type="webhook_subscription",
                  entity_id=sub_id, metadata={"client_id": client_id, **{k: body[k] for k in body if k != "secret"}}, ip=client_ip())
    return jsonify({"webhook": sub})


@bp.post("/<int:client_id>/webhooks/<int:sub_id>/rotate-secret")
@require_auth("admin")
def rotate_webhook_secret(client_id: int, sub_id: int):
    with _db().write_transaction() as conn:
        sub = hooks.rotate_subscription_secret(conn, client_id=client_id, sub_id=sub_id, master_key=_mk())
        svc.audit(conn, actor_user_id=_actor(), action="partner_webhook.secret_rotated", entity_type="webhook_subscription",
                  entity_id=sub_id, metadata={"client_id": client_id}, ip=client_ip())
    return jsonify({"webhook": sub}), 201


@bp.get("/<int:client_id>/webhooks/<int:sub_id>/deliveries")
@require_auth("admin")
def deliveries(client_id: int, sub_id: int):
    with _db().read_transaction() as conn:
        return jsonify({"items": hooks.list_deliveries(conn, client_id=client_id, sub_id=sub_id)})


@bp.post("/webhooks/run")
@require_auth("admin")
def run_worker():
    """Manual worker tick (bridge ORDER_CREATED + deliver due webhooks)."""
    return jsonify({"result": hooks.run_once(_db(), master_key=_mk())})
