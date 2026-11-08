/** Client workspace isolation. This is never a server authorization check. */
const OWNER = "60online_draft_owner_v1";
const BASES = ["60o_org_order_draft_v1", "60o_pack_builder_draft"];
let verifiedOwner = "guest";
function owner(): string { return verifiedOwner; }
export const scopedDraftKey = (base: string) => `${base}:${owner()}`;
export const pendingDraftKey = (base: string) => `${scopedDraftKey(base)}:pending`;
export function clearDraftOwner() { verifiedOwner="guest"; try { localStorage.removeItem(OWNER); } catch {} }
export function bindDraftOwner(id: number) {
  if (!Number.isSafeInteger(id) || id < 1) throw new Error("Invalid draft owner");
  verifiedOwner=String(id);
  try {
    localStorage.setItem(OWNER, String(id));
    for (const base of BASES) {
      const guestKey = `${base}:guest`, guest = localStorage.getItem(guestKey);
      if (!guest) continue;
      const destination = scopedDraftKey(base);
      // No private workspace is overwritten. Conflicts stay with this owner.
      localStorage.setItem(localStorage.getItem(destination) ? pendingDraftKey(base) : destination, guest);
      localStorage.removeItem(guestKey);
    }
  } catch { /* Auth still works when workspace persistence is unavailable. */ }
}
