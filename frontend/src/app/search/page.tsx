import { CatalogSkeleton } from "@/components/catalog/CatalogSkeleton";
import { Suspense } from "react";
import { CatalogBrowser } from "@/components/catalog/CatalogBrowser";
export const metadata = {
  title: "جستجوی کالا",
  robots: { index: false, follow: true },
};
export default function Search() {
  return (
    <Suspense fallback={<CatalogSkeleton />}>
      <CatalogBrowser />
    </Suspense>
  );
}
