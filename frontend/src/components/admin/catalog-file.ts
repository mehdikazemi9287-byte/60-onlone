/** The existing import API remains authoritative for rows and catalog identity. */
export const MAX_CSV_BYTES = 2_000_000;
// Header-only template: no invented product, SKU, price or publication request.
export const CATALOG_CSV_TEMPLATE = "\uFEFFcanonical_name_fa,category_slug\r\n";
export type CsvFile = { name: string; size: number; arrayBuffer(): Promise<ArrayBuffer> };

export async function readCatalogCsv(file: CsvFile): Promise<string> {
  if (!file.name.toLowerCase().endsWith(".csv")) {
    throw new Error("فایل باید CSV باشد؛ فایل Excel را به CSV UTF-8 تبدیل کنید.");
  }
  if (!Number.isSafeInteger(file.size) || file.size <= 0) {
    throw new Error("فایل خالی یا نامعتبر است.");
  }
  if (file.size > MAX_CSV_BYTES) throw new Error("حداکثر حجم فایل دو مگابایت است.");
  let bytes: ArrayBuffer;
  try { bytes = await file.arrayBuffer(); }
  catch { throw new Error("خواندن فایل انجام نشد؛ فایل را دوباره انتخاب کنید."); }
  if (bytes.byteLength !== file.size) throw new Error("فایل کامل خوانده نشد؛ دوباره انتخاب کنید.");
  let text: string;
  try { text = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
  catch { throw new Error("کدگذاری فایل باید UTF-8 باشد؛ دوباره با این فرمت ذخیره کنید."); }
  if (!text.trim() || text.includes("\u0000")) throw new Error("محتوای متنی CSV معتبر نیست.");
  return text;
}
