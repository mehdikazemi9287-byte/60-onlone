import { LegalCmsPage, legalMetadata } from "@/components/content/LegalCmsPage";

// Text comes from the CMS page listed in lib/legal-pages.ts; nothing is hard-coded here.
export const dynamic = "force-dynamic";
export function generateMetadata() {
  return legalMetadata("/terms/affiliate");
}
export default function AffiliateTermsPage() {
  return <LegalCmsPage path="/terms/affiliate" />;
}
