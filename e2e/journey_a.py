"""Journey A: consumer/household on mobile: browse -> product -> cart -> checkout -> withdrawal."""
import re, sys
sys.path.insert(0, "/tmp/e2e")
from common import *

EMAIL, PW = "demo@70online.ir", "Demo!2345"

with sync_playwright() as p:
    b, ctx, page = browser(p, mobile=True)
    visit(page, "/", "home")
    step("login demo (UI)", login_ui(page, EMAIL, PW))
    token = page.evaluate("() => localStorage.getItem('60online_token')")
    # clear cart via API for idempotent reruns
    s, cart = api("GET", "/cart", token=token)
    for it in (cart or {}).get("items", []) if s == 200 else []:
        api("DELETE", f"/cart/items/{it.get('id') or it.get('item_id')}", token=token)

    visit(page, "/search?q=" + "لپ", "search")
    visit(page, "/category/office", "category office")
    links = page.eval_on_selector_all("a[href^='/products/']", "els => els.map(e => e.getAttribute('href'))")
    step("category lists products", len(links) > 0, f"{len(links)} links")
    href = links[0] if links else "/products/laptop-asus-vivobook-15"
    visit(page, href, "product " + href)
    body = page.inner_text("body")
    step("VAT-inclusive price text", "مالیات" in body and "احتساب" in body,
         re.search(r"با احتساب[^\n]{0,40}", body).group(0) if "با احتساب" in body else "no 'با احتساب ... مالیات' text")
    step("'فروشندگان دیگر' block", page.locator("section[aria-label='فروشندگان دیگر']").count() > 0
         or "فروشندگان دیگر" in body, "")
    try:
        page.get_by_role("button", name=re.compile("افزودن به سبد")).first.click()
        page.wait_for_timeout(1500)
        s, cart = api("GET", "/cart", token=token)
        n = len(cart.get("items", [])) if s == 200 else 0
        step("add to cart", n > 0, f"cart items={n}")
    except Exception as e:
        step("add to cart", False, e)
        shot(page, "A_add_to_cart")

    visit(page, "/cart", "cart")
    visit(page, "/checkout", "checkout")
    try:
        inputs = page.locator("input.form-input, textarea.form-input")
        vals = ["کاربر آزمون", "09121234567", "تهران", "تهران", "خیابان آزادی، پلاک ۱۰، واحد ۲", "1234567890"]
        for i in range(min(inputs.count(), len(vals))):
            if not inputs.nth(i).input_value():
                inputs.nth(i).fill(vals[i])
        for _ in range(3):
            if page.locator("input[type=checkbox]").count():
                break
            nxt = page.get_by_role("button", name=re.compile("^ادامه"))
            if nxt.count() == 0:
                break
            nxt.first.click(); page.wait_for_timeout(1200)
        cb = page.locator("input[type=checkbox]")
        step("terms checkbox shown", cb.count() > 0, "")
        place = page.get_by_role("button", name=re.compile("ثبت سفارش|پرداخت"))
        place_btn = place.last
        step("place disabled before terms", place_btn.is_disabled(), "")
        cb.first.check()
        place_btn.click()
        page.wait_for_timeout(4000)
        page.wait_for_load_state("networkidle")
        txt = page.inner_text("body")
        m = re.search(r"/orders/([^/?#]+)", page.url)
        c = db()
        row = c.execute("SELECT order_number, status FROM orders WHERE user_id=(SELECT id FROM users WHERE email_normalized=?) ORDER BY id DESC LIMIT 1", (EMAIL,)).fetchone()
        order_no = m.group(1) if m else (row["order_number"] if row else None)
        step("checkout with mock card", row is not None and ("ثبت شد" in txt or m), f"url={page.url} order={dict(row) if row else None}")
        if not m and order_no:
            visit(page, f"/orders/{order_no}", "order page")
        else:
            step("order page", True, page.url)
        shot(page, "A_order_page")
        # terms acceptance evidence
        ta = c.execute("SELECT COUNT(*) n FROM terms_acceptances").fetchone()["n"]
        step("terms_acceptances row", ta > 0, f"rows={ta}")
        # mark delivered via DB (fulfillment_orders)
        oid = c.execute("SELECT id FROM orders WHERE order_number=?", (order_no,)).fetchone()["id"]
        fos = c.execute("SELECT id, status FROM fulfillment_orders WHERE order_id=?", (oid,)).fetchall()
        c.execute("UPDATE fulfillment_orders SET status='delivered', delivered_at=datetime('now') WHERE order_id=? "
                  "AND status NOT IN ('rejected','cancelled','pending_assignment')", (oid,))
        c.commit()
        step("fulfillments marked delivered", len(fos) > 0, f"fulfillments={[dict(f) for f in fos]}")
        visit(page, f"/orders/{order_no}", "order page after delivery")
        w = page.locator("#withdrawal-h")
        step("withdrawal card visible", w.count() > 0, "" if w.count() else "no #withdrawal-h")
        if w.count():
            page.get_by_role("button", name=re.compile("انصراف از این خرید")).click()
            page.wait_for_timeout(2000)
            st = page.locator("section[aria-labelledby=withdrawal-h] [role=status]").inner_text() if page.locator("section[aria-labelledby=withdrawal-h] [role=status]").count() else ""
            step("request withdrawal", "پذیرفته" in st, st)
        else:
            shot(page, "A_no_withdrawal")
            s, r = api("GET", f"/me/orders/{order_no}/withdrawal", token=token)
            print("withdrawal api:", s, str(r)[:300])
    except Exception as e:
        step("checkout flow", False, repr(e)[:300])
        shot(page, "A_checkout_fail")
    b.close()
summary("A")
