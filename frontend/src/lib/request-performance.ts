/** Pending requests only: never stores settled prices, balances or private responses. */
const pending = new Map<string, Promise<unknown>>();
let revision = 0;
export function invalidatePendingReads() {
  revision += 1;
  pending.clear();
}
export function coalesceRead<T>(key: string, run: () => Promise<T>): Promise<T> {
  const scopedKey = `${revision}:${key}`;
  const existing = pending.get(scopedKey);
  if (existing) return existing as Promise<T>;
  const task = run().finally(() => {
    if (pending.get(scopedKey) === task) pending.delete(scopedKey);
  });
  pending.set(scopedKey, task);
  return task;
}
/** Deadline covers response-body consumption, while preserving caller cancellation. */
export function deadline(parent?: AbortSignal | null, milliseconds = 30000) {
  const controller = new AbortController();
  const abort = () => controller.abort(parent?.reason);
  if (parent?.aborted) abort();
  else parent?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(() => controller.abort(new DOMException("مهلت دریافت پاسخ پایان یافت", "TimeoutError")), milliseconds);
  return {
    signal: controller.signal,
    dispose() { clearTimeout(timer); parent?.removeEventListener("abort", abort); },
  };
}
