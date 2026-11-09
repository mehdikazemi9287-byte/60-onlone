/**
 * Retail network (شبکهٔ فروشگاه‌های طرف قرارداد) — types and calls for backend/app/api/v1/retail_network.py.
 * Public endpoints return only branches of chains with an active contract; admin endpoints need role admin.
 */
import { apiRequest } from "@/lib/api";

export type NamedRef = { slug: string; name: string };

export type NetworkBranch = {
  id: number; title: string; chain: NamedRef; province: NamedRef; city: string | null; district: string | null;
  address: string | null; latitude: number | null; longitude: number | null; phone: string | null;
};

export type ProvinceCoverage = {
  slug: string; name: string; capital: string; center: [number, number];
  branches: number; chains: number; cities: number; covered: boolean;
};

export type CoverageResponse = {
  provinces: ProvinceCoverage[];
  totals: { provinces_covered: number; provinces: number; branches: number };
  center_note: string;
};

export type Sector = { id: number; slug: string; name: string; active: boolean };

export type PublicChain = {
  slug: string; name: string; brand_name: string | null; website: string | null;
  sectors: NamedRef[]; branches: number; provinces: number;
};

export type ChainDetail = Omit<PublicChain, "branches" | "provinces"> & { branches: NetworkBranch[]; truncated: boolean };

export type ProvinceDetail = {
  slug: string; name: string; capital: string; center: [number, number];
  branches: NetworkBranch[]; truncated: boolean; cities: { name: string; branches: number }[];
};

export const CONTRACT_STATUSES = ["prospect", "negotiating", "active", "paused", "ended"] as const;
export type ContractStatus = (typeof CONTRACT_STATUSES)[number];
export const STATUS_FA: Record<ContractStatus, string> = {
  prospect: "بالقوه", negotiating: "در حال مذاکره", active: "قرارداد فعال", paused: "متوقف", ended: "پایان‌یافته",
};
export const STATUS_CLASS: Record<ContractStatus, string> = {
  prospect: "bg-neutral-100 text-neutral-700", negotiating: "bg-amber-50 text-amber-800",
  active: "bg-green-50 text-green-800", paused: "bg-orange-50 text-orange-800", ended: "bg-red-50 text-red-700",
};

export const DATA_SOURCES = ["chain_file", "contract", "chain_website", "field_visit"] as const;
export const DATA_SOURCE_FA: Record<(typeof DATA_SOURCES)[number], string> = {
  chain_file: "فایل رسمی زنجیره", contract: "پیوست قرارداد", chain_website: "وبسایت زنجیره", field_visit: "بازدید میدانی",
};

export type AdminChain = {
  id: number; slug: string; name: string; brand_name: string | null; website: string | null;
  contract_status: ContractStatus; contract_signed_on: string | null; contract_reference: string | null;
  owner_user_id: number | null; supplier_id: number | null; provenance: "real" | "test"; notes: string | null;
  sectors: NamedRef[]; branch_counts: Record<ContractStatus, number>; province_count: number;
  created_at: string; updated_at: string;
};

export type AdminBranch = NetworkBranch & {
  branch_code: string; contract_status: ContractStatus; chain_contract_status: ContractStatus;
  supplier_location_id: number | null; data_source: (typeof DATA_SOURCES)[number]; source_reference: string;
  public: boolean; updated_at: string;
};

export type ImportResult = {
  committed: boolean; rows: number; created: number; updated: number; errors: number;
  results: { line: number; action: "create" | "update" | "error"; branch_code: string | null; error?: string; code?: string | null }[];
};

const qs = (params: Record<string, string | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const network = {
  branches: (f: { province?: string; sector?: string; chain?: string; city?: string; limit?: number } = {}) =>
    apiRequest<{ items: NetworkBranch[]; truncated: boolean }>(
      `/network${qs({ province: f.province, sector: f.sector, chain: f.chain, city: f.city, limit: f.limit ? String(f.limit) : undefined })}`),
  coverage: (sector?: string) => apiRequest<CoverageResponse>(`/network/coverage${qs({ sector })}`),
  sectors: () => apiRequest<{ items: Sector[] }>("/network/sectors"),
  chains: (sector?: string) => apiRequest<{ items: PublicChain[] }>(`/network/chains${qs({ sector })}`),
  chain: (slug: string) => apiRequest<ChainDetail>(`/network/chains/${encodeURIComponent(slug)}`),
  province: (slug: string) => apiRequest<ProvinceDetail>(`/network/provinces/${encodeURIComponent(slug)}`),
};

/** Group items by a key, keeping first-seen order (the API already sorts by province/city). */
export function groupBy<T>(items: T[], key: (t: T) => string): [string, T[]][] {
  const m = new Map<string, T[]>();
  for (const it of items) {
    const k = key(it);
    const arr = m.get(k);
    if (arr) arr.push(it); else m.set(k, [it]);
  }
  return [...m.entries()];
}

/** Absolute API URL for raw fetches (same rule as src/lib/api.ts). */
export const apiUrl = (path: string) => `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1${path}`;
