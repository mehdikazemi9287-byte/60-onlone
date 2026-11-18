// Jalali (Solar Hijri) ↔ Gregorian conversion — the standard jalaali-js algorithm (MIT), dependency-free.
const BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178];
const div = (a: number, b: number) => ~~(a / b), mod = (a: number, b: number) => a - ~~(a / b) * b;

function jalCal(jy: number) {
  let bl = BREAKS.length, gy = jy + 621, leapJ = -14, jp = BREAKS[0], jm = 0, jump = 0, n = 0;
  if (jy < jp || jy >= BREAKS[bl - 1]) throw new Error("سال خارج از محدوده");
  for (let i = 1; i < bl; i += 1) { jm = BREAKS[i]; jump = jm - jp; if (jy < jm) break; leapJ = leapJ + div(jump, 33) * 8 + div(mod(jump, 33), 4); jp = jm; }
  n = jy - jp; leapJ = leapJ + div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
  if (mod(jump, 33) === 4 && jump - n === 4) leapJ += 1;
  const leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150, march = 20 + leapJ - leapG;
  if (jump - n < 6) n = n - jump + div(jump + 4, 33) * 33;
  let leap = mod(mod(n + 1, 33) - 1, 4); if (leap === -1) leap = 4;
  return { leap, gy, march };
}
function g2d(gy: number, gm: number, gd: number) {
  let d = div((gy + div(gm - 8, 6) + 100100) * 1461, 4) + div(153 * mod(gm + 9, 12) + 2, 5) + gd - 34840408;
  d = d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752; return d;
}
function d2g(jdn: number) {
  let j = 4 * jdn + 139361631; j = j + div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908;
  const i = div(mod(j, 1461), 4) * 5 + 308, gd = div(mod(i, 153), 5) + 1, gm = mod(div(i, 153), 12) + 1;
  const gy = div(j, 1461) - 100100 + div(8 - gm, 6); return { gy, gm, gd };
}
function j2d(jy: number, jm: number, jd: number) { const r = jalCal(jy); return g2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1; }

/** "۱۴۰۵/۰۸/۰۱" or "1405-8-1" → "2026-10-23" (ISO), or null if invalid. */
export function jalaliToIso(input: string): string | null {
  const s = input.trim().replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)));
  const m = /^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$/.exec(s); if (!m) return null;
  const [jy, jm, jd] = [+m[1], +m[2], +m[3]];
  if (jm < 1 || jm > 12 || jd < 1 || jd > (jm <= 6 ? 31 : jm < 12 ? 30 : 30)) return null;
  try { const { gy, gm, gd } = d2g(j2d(jy, jm, jd)); return `${gy}-${String(gm).padStart(2, "0")}-${String(gd).padStart(2, "0")}`; } catch { return null; }
}
