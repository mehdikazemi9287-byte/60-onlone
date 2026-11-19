/** Read a bounded catalog with ordered output and at most four requests in flight. */
export async function readCatalogPages<T>(
  read: (page: number, signal: AbortSignal) => Promise<{ items: T[]; total_pages?: number }>,
  parent?: AbortSignal,
  timeoutMs = 30000,
): Promise<T[]> {
  const controller = new AbortController();
  const abort = () => controller.abort(parent?.reason);
  if (parent?.aborted) abort();
  else parent?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(() => controller.abort(new DOMException("Catalog deadline exceeded", "TimeoutError")), timeoutMs);
  try {
    const first = await read(1, controller.signal);
    const count = first.total_pages ?? 1;
    if (!Number.isSafeInteger(count) || count < 0) throw new Error("Invalid catalog pagination");
    const total = Math.min(50, Math.max(1, count));
    const items = [...first.items];
    for (let start = 2; start <= total; start += 4) {
      const pages = await Promise.all(Array.from({ length: Math.min(4, total - start + 1) }, (_, i) => read(start + i, controller.signal)));
      for (const page of pages) items.push(...page.items);
    }
    return items;
  } finally {
    clearTimeout(timer);
    parent?.removeEventListener("abort", abort);
    controller.abort(); // Cancel sibling fetches if one page failed.
  }
}
