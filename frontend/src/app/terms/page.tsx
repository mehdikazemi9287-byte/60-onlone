import { LegalCmsPage, legalMetadata } from "@/components/content/LegalCmsPage";

// Text comes from the CMS page listed in lib/legal-pages.ts; nothing is hard-coded here.
export const dynamic = "force-dynamic";
export function generateMetadata() {
  return legalMetadata("/terms");
}
export default function TermsPage() {
  return <LegalCmsPage path="/terms" />;
}
