"""Journey B: Gen Z on mobile: sign up, browse shops/brands, PWA install prompt, offline, stores."""
import re, sys, time
sys.path.insert(0, "/tmp/e2e")
from common import *

email = f"genz{int(time.time())}@example.com"
PW = "GenZ!23456"

with sync_playwright() as p:
    b, ctx, page = browser(p, mobile=True)
    visit(page, "/login", "login")
    otp_tab = page.get_by_role("button", name=re.compile("کد یک‌بار مصرف"))
    if otp_tab.count():
        otp_tab.first.click(); page.wait_for_timeout(300)
    otp_enabled = page.locator("input[type=tel]:not([disabled])").count() > 0
    step("OTP login available in dev", otp_enabled, "OTP tab is disabled ('به‌زودی'); no backend OTP route -> using email/password")
    visit(page, "/register", "register")
    try:
        page.fill("input[placeholder='نام و نام خانوادگی']", "سارا آزمون")
        page.fill("input[type=tel]", "۰۹۱۲۳۴۵۶۷۸۹")  # Persian digits on purpose
        page.fill("input[type=email]", email)
        pws = page.locator("input[type=password]")
        pws.nth(0).fill(PW); pws.nth(1).fill(PW)
        for cb in page.locator("form input[type=checkbox]").all():
            cb.check()
        page.locator("form button[type=submit]").last.click()
        page.wait_for_function("() => !!localStorage.getItem('60online_token')", timeout=10000)
        step("sign up (Persian-digit mobile)", True, email)
    except Exception as e:
        err = page.locator("[role=alert], .text-danger-600, .text-red-600").all_inner_texts()
        step("sign up (Persian-digit mobile)", False, f"{err} {repr(e)[:120]}")
        shot(page, "B_register_fail")
        login_ui(page, email, PW)
    step("log in after sign up", login_ui(page, email, PW))

    visit(page, "/shops", "shops")
    visit(page, "/brands", "brands")
    # PWA install prompt: fire a synthetic beforeinstallprompt and click the button
    visit(page, "/", "home (pwa)")
    page.evaluate("""() => { const e = new Event('beforeinstallprompt'); e.prompt = () => Promise.resolve();
        e.userChoice = Promise.resolve({outcome: 'dismissed'}); window.dispatchEvent(e); }""")
    page.wait_for_timeout(500)
    btn = page.locator("button", has_text=re.compile("نصب"))
    n_err = len(CONSOLE)
    if btn.count():
        btn.first.click(); page.wait_for_timeout(800)
        step("install-prompt button click no crash", len(CONSOLE) == n_err, CONSOLE[n_err:][:1])
    else:
        step("install-prompt button appears", False, "no button with 'نصب' after synthetic beforeinstallprompt")
    visit(page, "/offline", "offline")
    step("offline page has text", len(page.inner_text("body").strip()) > 20, page.inner_text("main")[:80] if page.locator("main").count() else "")
    visit(page, "/stores", "stores")
    page.fill("input[placeholder='مثلاً تهران']", "تهران")
    page.wait_for_timeout(1500)
    body = page.inner_text("body")
    step("stores city filter", "فروشگاه حضوری" in body or page.locator("li, article").count() > 0,
         "empty-state shown" if "ثبت نشده" in body else "results shown")
    b.close()
summary("B")
