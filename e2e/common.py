"""Shared helpers for 60Online E2E journeys."""
import json, os, sqlite3, sys, time, urllib.request
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000/api/v1"
DB = "/tmp/e2e/e2e.db"
SHOTS = "/tmp/e2e/shots"
os.makedirs(SHOTS, exist_ok=True)

RESULTS = []
CONSOLE = []


def step(name, ok, reason=""):
    RESULTS.append((name, bool(ok), str(reason)[:300]))
    print(f"{'PASS' if ok else 'FAIL'} | {name} | {str(reason)[:200]}", flush=True)
    return ok


def api(method, path, body=None, token=None, raw=False, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    h.update(headers or {})
    req = urllib.request.Request(API + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req) as r:
            b = r.read()
            return r.status, (b if raw else (json.loads(b) if b else None))
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b)
        except Exception:
            return e.code, b[:300]


def token_for(email, pw):
    s, r = api("POST", "/auth/login", {"email": email, "password": pw})
    return r.get("access_token") if s == 200 else None


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def browser(p, mobile=True):
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--headless=new"],
                          ignore_default_args=["--headless=old"])
    vp = {"width": 390, "height": 844} if mobile else {"width": 1280, "height": 800}
    ctx = b.new_context(viewport=vp, locale="fa-IR", is_mobile=mobile, has_touch=mobile)
    # The Next /api/v1 proxy is a read-only preview guard (405 on writes). Emulate the production
    # ingress (Nginx -> backend) for write calls by forwarding them straight to Flask.
    def fwd(route):
        r = route.request
        if r.method in ("GET", "HEAD", "OPTIONS"):
            return route.continue_()
        resp = route.fetch(url=r.url.replace(BASE, "http://127.0.0.1:8000"))
        route.fulfill(response=resp)

    ctx.route("**/api/v1/**", fwd)
    page = ctx.new_page()

    def on_console(m):
        if m.type == "error":
            CONSOLE.append((page.url, m.text[:120] + " @" + (m.location or {}).get("url", "")[-80:]))

    page.on("console", on_console)
    page.on("pageerror", lambda e: CONSOLE.append((page.url, "PAGEERROR " + str(e)[:200])))
    return b, ctx, page


def visit(page, path, label=None, wait="networkidle"):
    """Navigate and run generic checks: status, RTL, overflow at 390, console errors."""
    label = label or path
    before = len(CONSOLE)
    try:
        resp = page.goto(BASE + path, wait_until=wait, timeout=30000)
    except Exception as e:
        return step(f"visit {label}", False, e)
    page.wait_for_timeout(600)
    status = resp.status if resp else 0
    d = page.evaluate("() => ({dir: document.documentElement.dir, sw: document.documentElement.scrollWidth, iw: innerWidth})")
    errs = [e for e in CONSOLE[before:]]
    issues = []
    if status >= 400:
        issues.append(f"HTTP {status}")
    if d["dir"] != "rtl":
        issues.append(f"dir={d['dir']!r}")
    if d["sw"] > d["iw"]:
        issues.append(f"overflow sw={d['sw']}>iw={d['iw']}")
    hard = [e for e in errs if "Failed to load resource" not in e[1]]
    soft = [e[1].split("@")[-1] for e in errs if "Failed to load resource" in e[1]]
    if hard:
        issues.append(f"console: {hard[0][1]}")
    note = ("; WARN http-4xx/5xx: " + ", ".join(sorted(set(soft)))[:200]) if soft else ""
    return step(f"visit {label}", not issues, "; ".join(issues) + note)


def login_ui(page, email, pw, next_path="/"):
    page.goto(f"{BASE}/login?next={next_path}", wait_until="networkidle")
    page.fill("input[type=email]", email)
    page.fill("input[type=password]", pw)
    page.locator("input[type=password]").press("Enter")
    try:
        page.wait_for_function("() => !!localStorage.getItem('60online_token')", timeout=10000)
        return True
    except Exception:
        return False


def set_token(page, token):
    page.goto(BASE + "/offline", wait_until="domcontentloaded")
    page.evaluate("t => localStorage.setItem('60online_token', t)", token)


def shot(page, name):
    path = f"{SHOTS}/{name}.png"
    page.screenshot(path=path, full_page=False)
    return path


def summary(name):
    ok = sum(1 for r in RESULTS if r[1])
    print(f"== {name}: {ok}/{len(RESULTS)} passed")
    with open(f"/tmp/e2e/result_{name}.json", "w") as f:
        json.dump({"results": RESULTS, "console": CONSOLE}, f, ensure_ascii=False, indent=1)
