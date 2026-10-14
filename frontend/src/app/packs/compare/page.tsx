import { Suspense } from "react";
import { PackCompare } from "@/components/packs/PackViews";
export const metadata = { title: "مقایسه پک‌ها | شصت‌آنلاین", robots: { index: false } };
export default function Page() { return <Suspense><PackCompare /></Suspense>; }
