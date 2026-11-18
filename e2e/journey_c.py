"""Journey C: seller on desktop: sign up, /sell with Persian digits, admin approval, seller panel."""
import re, sys, time
sys.path.insert(0, "/tmp/e2e")
from common import *

ADMIN = token_for("admin@60online.ir", "Admin!2345")
step("admin login (API)", bool(ADMIN))
FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def seller(p, kind, nid):
    ts = str(int(time.time() * 1000))[-7:]
    email, pw = f"seller{kind}{ts}@example.com", "Seller!2345"
    b, ctx, page = browser(p, mobile=False)
    visit(page, "/register", f"[{kind}] register")
    page.fill("input[placeholder='نام و نام خانوادگی']", "فروشنده آزمون")
    page.fill("input[type=tel]", "09125550000")
    page.fill("input[type=email]", email)
    pws = page.locator("input[type=password]"); pws.nth(0).fill(pw); pws.nth(1).fill(pw)
    for cb in page.locator("form input[type=checkbox]").all():
        cb.check()
    page.locator("form button[type=submit]").last.click()
    try:
        page.wait_for_function("() => !!localStorage.getItem('60online_token')", timeout=10000)
        step(f"[{kind}] sign up", True, email)
    except Exception as e:
        step(f"[{kind}] sign up", False, e); shot(page, f"C_{kind}_signup"); b.close(); return
    visit(page, "/sell", f"[{kind}] /sell form")
    page.select_option("select", kind)
    vals = {"legal_name": "فروشگاه آزمون " + kind, "national_id": nid.translate(FA), "mobile": "09121112233".translate(FA),
            "shop_title": "غرفه آزمون " + kind, "shop_slug": f"e2e-{kind}-{ts}", "province": "تهران", "city": "تهران"}
    for k, v in vals.items():
        page.fill(f"#f-{k}", v)
    nid_val, mob_val = page.input_value("#f-national_id"), page.input_value("#f-mobile")
    step(f"[{kind}] Persian digits accepted in inputs", nid_val == nid and mob_val == "09121112233", f"nid={nid_val} mobile={mob_val}")
    page.locator("form input[type=checkbox]").last.check()
    page.get_by_role("button", name=re.compile("ثبت درخواست غرفه")).click()
    page.wait_for_timeout(2500)
    body = page.inner_text("body")
    ok = "غرفهٔ من" in body
    alert = page.locator("[role=alert]").all_inner_texts()
    step(f"[{kind}] submit application", ok, alert or ("pending" if "در انتظار" in body else ""))
    if not ok:
        shot(page, f"C_{kind}_apply_fail"); b.close(); return
    s, apps = api("GET", "/admin/shop-applications", token=ADMIN)
    items = apps.get("items", apps.get("applications", [])) if isinstance(apps, dict) else []
    mine = [a for a in items if (a.get("shop_slug") or a.get("slug")) == vals["shop_slug"]]
    step(f"[{kind}] admin lists application", s == 200 and mine, f"status={s} n={len(items)} keys={list(items[0])[:8] if items else apps}")
    if mine:
        sid = mine[0].get("supplier_id") or mine[0].get("id")
        s, r = api("POST", f"/admin/shop-applications/{sid}/review", {"decision": "approve", "note": "E2E"}, token=ADMIN)
        step(f"[{kind}] admin approves", s == 200, f"{s} {str(r)[:120]}")
        c = db()
        au = c.execute("SELECT COUNT(*) n FROM audit_logs WHERE entity_id=? AND action LIKE 'shop_application%'", (str(sid),)).fetchone()["n"] \
            if c.execute("SELECT name FROM sqlite_master WHERE name='audit_logs'").fetchone() else -1
        step(f"[{kind}] audit row for shop review", au > 0, f"audit rows={au}")
    visit(page, "/sell", f"[{kind}] seller panel")
    body = page.inner_text("body")
    step(f"[{kind}] panel shows balance", "قابل تسویه" in body and "در امانت" in body, "")
    nav = page.locator("nav[aria-label='ابزارهای فروشنده']")
    navtxt = nav.inner_text() if nav.count() else ""
    for t in ["ارسال سفارش‌ها", "خروجی مالی", "مراجعهٔ حضوری"]:
        step(f"[{kind}] tool '{t}'", t in navtxt, "")
    has_brand = "ثبت برند" in navtxt
    step(f"[{kind}] brand registration only for brand", has_brand == (kind == "brand"), f"brand tool shown={has_brand}")
    if kind == "brand":
        shot(page, "C_brand_panel")
    b.close()


def nat_id():
    import random
    d = [random.randint(0, 9) for _ in range(9)]
    r = sum(x * (10 - i) for i, x in enumerate(d)) % 11
    return "".join(map(str, d)) + str(r if r < 2 else 11 - r)


with sync_playwright() as p:
    seller(p, "shop", nat_id())
    seller(p, "brand", nat_id())
summary("C")
