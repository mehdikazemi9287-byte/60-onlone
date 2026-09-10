import { PackBuilderInteractive } from "./PackBuilderInteractive";

// Smart 60 Pack Builder — restored to its original homepage location (#pack-builder).
// Recommendation engine + budget/occasion/editing logic: src/lib/pack-builder.ts
// (ported verbatim from the pre-Next.js storefront). Not a standalone route.
export function PackBuilder() {
  return (
    <section id="pack-builder" className="section-shell scroll-mt-28" aria-labelledby="pack-builder-title">
      <div className="container-page">
        <div className="section-heading">
          <div>
            <span className="section-kicker">خرید گروهی</span>
            <h2 id="pack-builder-title">پک‌ساز هوشمند ۶۰</h2>
            <p>بودجه و مناسبت را انتخاب کنید تا سه پک پیشنهادی (اقتصادی، متعادل، ویژه) از کالاهای واقعیِ دارای قیمت رسمی ساخته شود؛ یا پک سفارشی بسازید و کالاها را ویرایش/جایگزین کنید.</p>
          </div>
        </div>
        <PackBuilderInteractive />
      </div>
    </section>
  );
}
