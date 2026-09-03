import raw from "./catalogRaw.json";

export interface CatalogItem {
  id: number;
  slug: string;
  name: string;
  brand: string | null;
  categorySlug: string;
  categoryLabel: string;
  priceMinor: number;
  /** true when the source catalog left price_minor blank (draft row) and this
   *  is a modeled estimate by unit/category rather than an official price. */
  priceEstimated: boolean;
  unit: string | null;
  hasPhoto: boolean;
}

// 77 real SKUs sourced from the official 60Online catalog export
// (catalog_official_products_v2.csv — protein-fresh, nuts-local, supermarket,
// fresh-dairy-frozen, gift-seasonal). Every row's image_url is empty in the
// source data, so these render as clean neutral placeholder tiles rather than
// photography — see PackBuilder's CatalogThumb component. 48 of the 77 rows
// also had no price_minor (draft entries); those get a modeled per-kg/per-unit
// estimate instead (priceEstimated: true) so the budget calculator still works,
// while nuts-local/gift-seasonal/a few protein-fresh rows use official prices.
export const CATALOG_ITEMS: CatalogItem[] = raw as CatalogItem[];
