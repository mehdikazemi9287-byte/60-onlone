import { NextRequest } from "next/server";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
async function proxy(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const origin = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000";
  const url = new URL(
    "/api/v1/" + (await params).path.map(encodeURIComponent).join("/"),
    origin,
  );
  url.search = request.nextUrl.search;
  const headers = new Headers();
  for (const name of [
    "content-type",
    "authorization",
    "idempotency-key",
    "accept",
  ]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const maximum = 3 * 1024 * 1024;
    const tooLarge = () =>
      Response.json(
        {
          error: {
            code: "payload_too_large",
            message: "حجم درخواست بیش از حد مجاز است.",
          },
        },
        { status: 413 },
      );
    if (Number(request.headers.get("content-length")) > maximum)
      return tooLarge();
    let body: ArrayBuffer | undefined;
    if (!["GET", "HEAD"].includes(request.method) && request.body) {
      const reader = request.body.getReader();
      const chunks: Uint8Array[] = [];
      let length = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        length += value.byteLength;
        if (length > maximum) {
          await reader.cancel();
          return tooLarge();
        }
        chunks.push(value);
      }
      const bytes = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
      body = bytes.buffer;
    }
    const upstream = await fetch(url, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(30000),
    });
    const out = new Headers();
    for (const name of [
      "content-type",
      "retry-after",
      "location",
      "www-authenticate",
    ]) {
      const value = upstream.headers.get(name);
      if (value) out.set(name, value);
    }
    out.set("Cache-Control", "no-store");
    return new Response(upstream.body, {
      status: upstream.status,
      headers: out,
    });
  } catch {
    return Response.json(
      {
        error: {
          code: "backend_unavailable",
          message: "ارتباط با سرویس برقرار نشد؛ دوباره تلاش کنید.",
        },
      },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
  proxy as HEAD,
  proxy as OPTIONS,
};
