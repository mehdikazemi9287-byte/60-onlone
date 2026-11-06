# وب‌سرویس شرکای ۶۰آنلاین (Partner API v1)

- پایه: `/api/partner/v1` — سند OpenAPI 3.1: `GET /api/partner/v1/openapi.json`
- احراز هویت: سرآیند `X-Api-Key: <prefix>.<secret>` (کلید فقط یک بار هنگام صدور نمایش داده می‌شود؛ فقط هش SHA-256 ذخیره می‌شود).
- مبالغ: ریال صحیح در فیلدهای `*_minor`.
- صفحه‌بندی: `?limit=1..100&cursor=<next_cursor>`؛ پاسخ: `{"data": [...], "next_cursor": "..." | null}`.
- خطا: `{"error": {"code": "...", "message": "...", "details": {...}}}` — کدهای رایج: `invalid_api_key`، `api_key_revoked`، `insufficient_scope`، `rate_limited` (۴۲۹ + `Retry-After`)، `invalid_signature`، `idempotency_conflict`.
- مجوزها (scope): `catalog:read`، `offers:write`، `orders:read`، `orders:write`، `shipments:write`، `invoices:read`، `credit:read`.

## مسیرها

| متد | مسیر | scope |
|---|---|---|
| GET | `/me` | — |
| GET | `/catalog/products` ، `/catalog/offers?product_id=` | catalog:read |
| GET / PUT | `/offers` (فقط پیشنهادهای تأمین‌کننده صاحب کلید) | offers:write |
| GET | `/orders` ، `/orders/<order_number>` | orders:read |
| POST | `/shipments/<id>/status` | shipments:write |
| GET | `/credit/balance` (کلید سازمانی) | credit:read |
| POST | `/inbound/<source>` | بسته به منبع |

```bash
curl -H "X-Api-Key: $KEY" "https://60online.ir/api/partner/v1/catalog/products?limit=20"
curl -X PUT -H "X-Api-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"product_id": 12, "selling_price_minor": 1500000, "stock_quantity": 40}' \
     https://60online.ir/api/partner/v1/offers
```

## امضا (ورودی و خروجی)

سرآیند `X-60Online-Signature: t=<unix>,v1=<hex>` که در آن
`v1 = HMAC_SHA256(secret, t + "." + raw_body)`. اختلاف زمان بیش از ۳۰۰ ثانیه رد می‌شود.
کلید امضای ورودی از پنل مدیر (`signing-secret/rotate`) و کلید هر وب‌هوک هنگام ساخت اشتراک یک بار نمایش داده می‌شود.

### وب‌سرویس ورودی

منابع ثبت‌شده: `supplier.price_stock` (offers:write) و `shipment.tracking` (shipments:write).
سرآیند `Idempotency-Key` الزامی است؛ تکرار با همان بدنه همان نتیجه را برمی‌گرداند (`replayed: true`) و با بدنهٔ متفاوت ۴۰۹ می‌دهد.

```bash
BODY='{"items":[{"supplier_sku":"A-1","selling_price_minor":1200000,"stock_quantity":7}]}'
TS=$(date +%s)
SIG=$(printf '%s' "$TS.$BODY" | openssl dgst -sha256 -hmac "$SIGNING_SECRET" | awk '{print $2}')
curl -X POST https://60online.ir/api/partner/v1/inbound/supplier.price_stock \
  -H "X-Api-Key: $KEY" -H "Idempotency-Key: feed-2026-11-06-01" \
  -H "X-60Online-Signature: t=$TS,v1=$SIG" -H "Content-Type: application/json" -d "$BODY"
```

### وب‌هوک خروجی

رویدادها: `order.created`، `order.status_changed`، `offer.stock_low`، `settlement.completed`، `credit.statement_issued`.
بدنه: `{"id":"evt_..","type":"..","created_at":"..","data":{..}}`. پاسخ 2xx یعنی تحویل؛ در غیر این صورت با تأخیر نمایی (۳۰ ثانیه تا ۱ ساعت، حداکثر ۸ بار) تکرار می‌شود. فقط `https` روی درگاه ۴۴۳ و میزبان عمومی پذیرفته می‌شود.

بررسی امضا در سمت شما:

```python
import hmac, hashlib, time
def verify(secret, header, body: bytes):
    p = dict(x.split("=", 1) for x in header.split(","))
    if abs(time.time() - int(p["t"])) > 300: return False
    mac = hmac.new(secret.encode(), p["t"].encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, p["v1"])
```

```php
function verify60($secret, $header, $body) {
    parse_str(str_replace(',', '&', $header), $p);
    if (abs(time() - (int)$p['t']) > 300) return false;
    $mac = hash_hmac('sha256', $p['t'] . '.' . $body, $secret);
    return hash_equals($mac, $p['v1']);
}
// $ok = verify60($secret, $_SERVER['HTTP_X_60ONLINE_SIGNATURE'], file_get_contents('php://input'));
```

```js
const crypto = require("crypto");
function verify(secret, header, rawBody) {
  const p = Object.fromEntries(header.split(",").map(s => s.split("=")));
  if (Math.abs(Date.now() / 1000 - Number(p.t)) > 300) return false;
  const mac = crypto.createHmac("sha256", secret).update(`${p.t}.${rawBody}`).digest("hex");
  return mac.length === p.v1.length && crypto.timingSafeEqual(Buffer.from(mac), Buffer.from(p.v1));
}
```

## مدیریت (ادمین)

`/api/v1/admin/partner-clients` — ساخت مشتری (+ صدور کلید)، `PATCH` مجوز/سقف نرخ/وضعیت،
`POST /<id>/keys`، `/<id>/keys/<kid>/rotate|revoke`، `/<id>/signing-secret/rotate`،
`GET|POST /<id>/webhooks`، `PATCH /<id>/webhooks/<sid>`، `/<id>/webhooks/<sid>/rotate-secret|deliveries`،
`GET /<id>/inbound`، `POST /webhooks/run` (اجرای دستی صف).
