import type { Metadata } from "next";
import { PackPage } from "@/components/packs/PackViews";
import { serverPack, site } from "@/lib/server-catalog";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const pack = await serverPack(slug).catch(() => null);
  const canonical = `${site}/packs/${encodeURIComponent(slug)}`;
  if (!pack) return { title: "پک", alternates: { canonical }, robots: { index: false, follow: true } };
  const description = (pack.description_fa || pack.purpose_fa || "").slice(0, 160) || undefined;
  return {
    title: pack.title_fa,
    description,
    alternates: { canonical },
    openGraph: { title: pack.title_fa, description, url: canonical, ...(pack.image_url ? { images: [pack.image_url] } : {}) },
  };
}

export default async function Page({ params }: { params: Promise<{ slug: string }> }) { return <PackPage slug={(await params).slug} />; }
