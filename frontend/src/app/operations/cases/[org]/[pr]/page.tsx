import OpsCase from "@/components/operations/OpsCase";

export const metadata = { title: "پرونده عملیات | 60Online", robots: { index: false, follow: false } };

export default async function Page({ params }: { params: Promise<{ org: string; pr: string }> }) {
  const { org, pr } = await params;
  return <OpsCase org={org} pr={pr} />;
}
