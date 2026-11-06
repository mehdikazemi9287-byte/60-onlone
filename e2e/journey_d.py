"""Journey D: organization admin / employee on desktop: /organization pages render, no crashes."""
import sys
sys.path.insert(0, "/tmp/e2e")
from common import *

PAGES = ["/organization", "/organization/b2b-orders", "/organization/statement", "/organization/credit",
         "/organization/welfare", "/organization/buying-rules", "/organization/orders", "/organization/members",
         "/organization/finance", "/organization/requests", "/organization/benefits", "/organization/policy"]
CRASH = ["Application error", "client-side exception", "Unhandled Runtime Error", "This page could not be found"]

with sync_playwright() as p:
    for who, email, pw in [("org_admin", "hr@parsco.ir", "Hr!23456789"), ("employee", "alice@parsco.ir", "Alice!23456")]:
        b, ctx, page = browser(p, mobile=False)
        step(f"[{who}] login (UI)", login_ui(page, email, pw, "/organization"))
        for path in (PAGES if who == "org_admin" else PAGES[:6]):
            visit(page, path, f"[{who}] {path}")
            page.wait_for_timeout(500)
            body = page.inner_text("body")
            crash = [c for c in CRASH if c in body]
            h = page.locator("main h1, h1").first
            title = h.inner_text()[:40] if h.count() else ""
            step(f"[{who}] {path} renders", not crash and len(body) > 200, crash or f"h1={title!r}")
            if crash:
                shot(page, f"D_{who}_{path.strip('/').replace('/', '_')}")
        b.close()
    # mobile overflow check of the newest org pages
    b, ctx, page = browser(p, mobile=True)
    login_ui(page, "hr@parsco.ir", "Hr!23456789", "/organization")
    for path in PAGES[1:6]:
        visit(page, path, f"[org_admin 390px] {path}")
    b.close()
summary("D")
