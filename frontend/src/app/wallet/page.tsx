import AccountPanel from "@/components/AccountPanel";
export const metadata = { robots: { index: false, follow: false } };
export default function Page() {
  return <AccountPanel section="wallet" />;
}
