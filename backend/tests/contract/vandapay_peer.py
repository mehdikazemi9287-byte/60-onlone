"""Test-only IPC peer. Imports a separately supplied VandaPay source checkout.

No private source is bundled here. All DBs, merchants and keys are synthetic and
temporary; network access is forbidden. This is not a deployed staging test.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import traceback


def main():
    protocol = sys.stdout
    sys.stdout = sys.stderr  # application/dev-SMS output must not corrupt the JSON protocol
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root / "backend"))

    def no_network(*args, **kwargs):
        raise RuntimeError("contract peer forbids external network")
    socket.socket.connect = no_network
    socket.create_connection = no_network

    from app import create_app, ledger, policy
    from app.config import DEV_FERNET_KEY, DEV_JWT_SECRET, DEV_PEPPER
    from app.migrate import migrate
    spec = importlib.util.spec_from_file_location("vp_contract_fixtures", root / "backend/tests/conftest.py")
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    with tempfile.TemporaryDirectory(prefix="vp-contract-") as tmp:
        app = create_app({"DATABASE_URL": f"sqlite:///{tmp}/test.sqlite3", "APP_ENV": "test",
                          "JWT_SECRET": DEV_JWT_SECRET, "FERNET_KEY": DEV_FERNET_KEY, "SECRET_PEPPER": DEV_PEPPER,
                          "RATE_LIMIT_ENABLED": "0", "WEBHOOK_INLINE": "0", "JOBS_INLINE": "0",
                          "OTP_DEV_ECHO": "1", "SMS_PROVIDER": "console", "LIVE_PSP_PROVIDER": "none",
                          "PUBLIC_BASE_URL": "https://api.test", "CHECKOUT_BASE_URL": "https://pay.test"})
        migrate(app.extensions["vp_engine"])
        app.extensions["vp_webhook_transport"] = fixtures.Recorder()
        client = app.test_client()
        h = fixtures.Helpers(app, client)
        merchant = h.merchant(categories=("goods", "services"), rates={"org_credit": 150, "card": 100})
        key = h.api_key(merchant["id"])
        print(json.dumps({"key": key, "webhook_secret": merchant["webhook_secret"]}), file=protocol, flush=True)
        intents, tokens = {}, {}
        try:
            for raw in sys.stdin:
                cmd = json.loads(raw)
                if cmd["op"] == "http":
                    resp = client.open(cmd["path"], method=cmd["method"], headers=cmd["headers"], json=cmd["body"])
                    data = resp.get_json()
                    if cmd["path"] == "/api/v1/payment_intents" and resp.status_code == 201:
                        intents[data["id"]] = data
                    result = {"status": resp.status_code, "body": data}
                elif cmd["op"] == "fund":
                    intent = intents[cmd["intent_id"]]
                    org = h.org()
                    phone, purses = h.phone(), {}
                    for name, rules in {
                        "travel": {"categories": ["travel"]},
                        "sku": {"categories": ["goods"], "product_allowlist": [cmd["sku"]]},
                    }.items():
                        program = h.program(org["id"], rules=rules)
                        h.member_with_credit(org["id"], program, cmd["amount"], phone=phone)
                        purses[name] = h.purse_of(phone, program["id"])["id"]
                    tokens[intent["id"]] = h.login_checkout(intent, phone)
                    result = {"purses": purses, "options": h.options(intent, tokens[intent["id"]])}
                elif cmd["op"] == "confirm":
                    intent = intents[cmd["intent_id"]]
                    resp = h.confirm(intent, tokens[intent["id"]], cmd["allocation"], key=cmd["key"])
                    result = {"status": resp.status_code, "body": resp.get_json()}
                elif cmd["op"] == "sandbox":
                    result = h.sandbox(cmd["url"], cmd["outcome"])
                elif cmd["op"] == "balances":
                    with h.conn() as conn:
                        result = {"purse": policy.purse_amounts(conn, cmd["purse_id"]),
                                  "trial": ledger.trial_balance(conn)}
                else:
                    raise ValueError("unknown test command")
                print(json.dumps(result, ensure_ascii=False), file=protocol, flush=True)
        finally:
            app.extensions["vp_engine"].dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
