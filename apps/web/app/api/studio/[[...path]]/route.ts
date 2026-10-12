import { NextRequest } from "next/server";

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const limit = 25 * 1024 * 1024 + 65536;
type Context = { params: Promise<{ path?: string[] }> };
const error = (detail: string, status: number) => Response.json({ detail }, { status, headers: { "Cache-Control": "no-store" } });

export async function proxy(request: NextRequest, context: Context) {
  const { path = [] } = await context.params;
  const get = request.method === "GET";
  const upload = request.method === "POST" && path.join("/") === "upload";
  const source = path[0] === "sources" && uuid.test(path[1] ?? "");
  const annotation = source && path[2] === "annotations";
  const allowed = (get && path.join("/") === "sources") || upload || (source && (
    (get && path.length === 3 && ["status", "pages", "file", "annotations"].includes(path[2])) ||
    (request.method === "POST" && path.length === 3 && ["render", "annotations"].includes(path[2])) ||
    (get && path.length === 5 && path[2] === "pages" && path[4] === "image" && /^[1-9]\d{0,2}$/.test(path[3]) && Number(path[3]) <= 200) ||
    (annotation && uuid.test(path[3] ?? "") && ((request.method === "PATCH" && path.length === 4) || (get && path.length === 5 && path[4] === "crop")))
  ));
  if (!allowed) return error("Not found", 404);
  const authorization = request.headers.get("authorization");
  if (!authorization) return error("Sign-in required", 401);
  const headers: Record<string, string> = { Authorization: authorization };
  let exceeded = false;
  let body: ReadableStream<Uint8Array> | undefined;
  if (upload || (!get && annotation)) {
    const key = request.headers.get("idempotency-key") ?? "";
    if (upload && !uuid.test(key)) return error("A UUID Idempotency-Key is required", 422);
    const type = request.headers.get("content-type") ?? "";
    if (upload && !type.toLowerCase().startsWith("multipart/form-data;")) return error("A multipart PDF upload is required", 415);
    if (request.headers.get("content-encoding") && request.headers.get("content-encoding") !== "identity") return error("Compressed uploads are unsupported", 415);
    const length = request.headers.get("content-length");
    if (length && (!/^\d+$/.test(length) || Number(length) > (upload ? limit : 96 * 1024))) return error("Upload exceeds the size limit", 413);
    headers["Content-Type"] = type; if (upload) headers["Idempotency-Key"] = key;
    const reader = request.body?.getReader();
    if (!reader) return error("Missing upload", 400);
    let size = 0;
    body = new ReadableStream({ async pull(controller) {
      try {
        const chunk = await reader.read();
        if (chunk.done) { controller.close(); return; }
        size += chunk.value.byteLength;
        if (size > (upload ? limit : 96 * 1024)) { exceeded = true; await reader.cancel(); controller.error(new Error("body_limit")); return; }
        controller.enqueue(chunk.value);
      } catch { controller.error(new Error("upload_interrupted")); }
    }, cancel: () => reader.cancel() });
  }
  try {
    const init: RequestInit & { duplex?: "half" } = { method: request.method, headers, cache: "no-store", signal: AbortSignal.timeout(upload ? 120000 : 60000) };
    if (body) { init.body = body; init.duplex = "half"; }
    let target = "/v1/admin/studio/" + path.join("/");
    if (upload) target = "/v1/admin/knowledge/upload";
    if (source && path.length === 3 && ["file", "status"].includes(path[2])) target = `/v1/admin/knowledge/${path[1]}/${path[2]}`;
    const response = await fetch(`${process.env.ADMIN_API_INTERNAL_URL ?? "http://localhost:8001"}${target}`, init);
    const output = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    for (const name of ["Content-Type", "Content-Disposition", "Content-Security-Policy"]) {
      const value = response.headers.get(name); if (value) output.set(name, value);
    }
    return new Response(response.body, { status: response.status, headers: output });
  } catch { return error(exceeded ? "Upload exceeds the size limit" : "Service unavailable", exceeded ? 413 : 503); }
}
export const GET = proxy;
export const POST = proxy;

export const PATCH = proxy;
