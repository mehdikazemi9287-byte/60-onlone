import RequestTracking from "@/components/RequestTracking";
export const metadata = { title: "پیگیری درخواست | شصت‌آنلاین", robots: { index: false } };
export default async function Page({ params }: { params: Promise<{ id: string }> }) { return <RequestTracking id={(await params).id} />; }
