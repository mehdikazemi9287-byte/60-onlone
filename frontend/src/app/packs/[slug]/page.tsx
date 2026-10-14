import { PackPage } from "@/components/packs/PackViews";
export const metadata = { title: "پک | شصت‌آنلاین" };
export default async function Page({ params }: { params: Promise<{ slug: string }> }) { return <PackPage slug={(await params).slug} />; }
