/** Legal/contact routes backed by CMS pages (admin → مدیریت محتوا). No legal text lives in code:
 * the owner creates a CMS page with `cmsSlug` (kind «صفحه») and publishes it. Until then the route
 * shows a neutral "coming soon" notice. `canonical` is the one indexable URL for that text. */
export type LegalPage = { path: string; cmsSlug: string; canonical: string; title: string };
export const LEGAL_PAGES: LegalPage[] = [
  { path: "/terms", cmsSlug: "help-terms", canonical: "/help/terms", title: "شرایط استفاده" },
  { path: "/privacy", cmsSlug: "help-privacy", canonical: "/help/privacy", title: "حریم خصوصی" },
  { path: "/contact", cmsSlug: "contact", canonical: "/contact", title: "تماس با ما" },
  { path: "/terms/affiliate", cmsSlug: "terms-affiliate", canonical: "/terms/affiliate", title: "قوانین همکاری در فروش" },
];
export const LEGAL_COMING_SOON = "متن این صفحه به‌زودی منتشر می‌شود.";
export function legalPage(path: string): LegalPage {
  const p = LEGAL_PAGES.find((x) => x.path === path);
  if (!p) throw new Error("unknown legal page " + path);
  return p;
}
