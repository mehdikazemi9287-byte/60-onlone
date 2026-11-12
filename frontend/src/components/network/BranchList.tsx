import Link from "next/link";
import type { NetworkBranch } from "@/lib/network";

/** One branch card; the chain links to its page unless we are already on it. */
export function BranchCard({ b, showChain = true }: { b: NetworkBranch; showChain?: boolean }) {
  return (
    <li className="rounded-2xl border border-neutral-200 bg-white p-4">
      <p className="font-bold text-neutral-900">{b.title}</p>
      {showChain && (
        <p className="mt-0.5 text-xs text-neutral-500">
          <Link className="underline" href={`/network/chain/${encodeURIComponent(b.chain.slug)}`}>{b.chain.name}</Link>
        </p>
      )}
      <p className="mt-1 text-sm text-neutral-600">
        {[b.province.name, b.city, b.district, b.address].filter(Boolean).join("، ")}
      </p>
      {b.phone && <p className="text-sm" dir="ltr">{b.phone}</p>}
    </li>
  );
}

export function TruncatedNote({ truncated }: { truncated: boolean }) {
  if (!truncated) return null;
  return <p className="mt-3 text-sm text-amber-700">فهرست طولانی است و فقط بخشی از شعبه‌ها نمایش داده شد.</p>;
}
