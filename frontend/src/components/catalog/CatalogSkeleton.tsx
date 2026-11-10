/** Stable card geometry, without invented products or prices. */
export function CatalogSkeleton() {
  return <div role="status" aria-label="در حال دریافت کالاها" aria-busy="true">
    <span className="sr-only">در حال دریافت کالاها…</span>
    <div aria-hidden="true" className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4 motion-safe:animate-pulse">
      {Array.from({ length: 8 }, (_, i) => <div key={i} className="overflow-hidden rounded-xl border border-neutral-200 bg-white p-4">
        <div className="mb-4 aspect-square rounded-lg bg-neutral-100" />
        <div className="mb-3 h-4 w-4/5 rounded bg-neutral-100" />
        <div className="h-4 w-1/2 rounded bg-neutral-100" />
      </div>)}
    </div>
  </div>;
}
