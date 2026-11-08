/** Loading UI only: no synthetic product, price, stock or image data. */
export function CatalogLoading() {
  return <div className="catalog-loading" role="status" aria-label="در حال دریافت کالاها" aria-busy="true">
    <p className="sr-only">در حال دریافت کالاها…</p>
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-3" aria-hidden="true">
      {Array.from({ length: 6 }, (_, index) => <div key={index} className="rounded-2xl bg-white p-4">
        <div className="skeleton mb-4 aspect-[4/3] rounded-xl" />
        <div className="skeleton mb-3 h-4 w-3/4 rounded" />
        <div className="skeleton h-4 w-1/2 rounded" />
      </div>)}
    </div>
  </div>;
}
