"""Journey F: recurring list (/me/recurring) create and preview (mobile)."""
import re, sys
sys.path.insert(0, "/tmp/e2e")
from common import *

with sync_playwright() as p:
    b, ctx, page = browser(p, mobile=True)
    step("login demo (UI)", login_ui(page, "demo@70online.ir", "Demo!2345", "/me/recurring"))
    visit(page, "/me/recurring", "recurring")
    try:
        page.get_by_role("button", name="ساخت فهرست جدید").click()
        page.fill("input[placeholder^='مثلاً خرید هفتگی']", "خرید ماهانه آزمون")
        page.fill("#rec-search", "کاغذ")
        page.wait_for_timeout(1500)
        hits = page.locator("ul li button")
        step("product search in list form", hits.count() > 0, f"hits={hits.count()}")
        hits.first.click()
        page.get_by_role("button", name="ساخت فهرست").click()
        page.wait_for_timeout(2000)
        body = page.inner_text("body")
        step("create recurring list", "خرید ماهانه آزمون" in body, "")
        page.get_by_role("button", name="پیش‌فاکتور").first.click()
        page.wait_for_timeout(2000)
        body = page.inner_text("body")
        step("preview (پیش‌فاکتور)", "قابل پرداخت" in body, re.search(r"قابل پرداخت[^\n]*\n?[^\n]*", body).group(0)[:60] if "قابل پرداخت" in body else body[-200:])
        d = page.evaluate("() => document.documentElement.scrollWidth - innerWidth")
        step("no overflow after preview", d <= 0, f"overflow={d}")
        shot(page, "F_recurring_preview")
    except Exception as e:
        step("recurring flow", False, repr(e)[:200]); shot(page, "F_fail")
    b.close()
summary("F")
