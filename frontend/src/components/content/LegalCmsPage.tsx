import type { Metadata } from "next";
import { ContentRenderer } from "./ContentRenderer";
import { UnavailablePage } from "./UnavailablePage";
import { contentMetadata, publishedContent } from "@/lib/published-content";
import { LEGAL_COMING_SOON, legalPage } from "@/lib/legal-pages";

export async function legalMetadata(path: string): Promise<Metadata> {
  const p = legalPage(path);
  const d = await publishedContent(p.cmsSlug);
  const meta = contentMetadata(d && d.kind === "page" ? d : null, p.title, p.canonical);
  // Nothing published yet: keep the placeholder out of search results.
  return d && d.kind === "page" ? meta : { ...meta, robots: { index: false, follow: true } };
}

export async function LegalCmsPage({ path }: { path: string }) {
  const p = legalPage(path);
  const d = await publishedContent(p.cmsSlug);
  if (!d || d.kind !== "page") return <UnavailablePage title={p.title} message={LEGAL_COMING_SOON} />;
  return (
    <article className="mx-auto w-full max-w-[1280px] px-4 py-8">
      <h1 className="px-6 text-2xl font-bold">{d.content.title}</h1>
      <ContentRenderer content={d.content} />
    </article>
  );
}
