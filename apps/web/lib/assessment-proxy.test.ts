import { afterEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "../app/api/assessments/[[...path]]/route";
const id = "12345678-1234-1234-1234-123456789abc";
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
it("refuses arbitrary destinations, methods and unauthenticated images", async () => {
  const upstream = vi.fn(); vi.stubGlobal("fetch", upstream);
  for (const path of [["https:", "evil.test"], [id, "publish"], [id, "pages", "201", "image"]]) expect((await GET(new NextRequest("http://localhost/api/assessments"), { params: Promise.resolve({ path }) })).status).toBe(404);
  expect((await GET(new NextRequest("http://localhost/api/assessments"), { params: Promise.resolve({ path: [id, "pages", "1", "image"] }) })).status).toBe(401);
  expect(upstream).not.toHaveBeenCalled();
});
it("streams only the authorized fixed image route without scope headers or query", async () => {
  vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
  const upstream = vi.fn().mockResolvedValue(new Response("synthetic png", { headers: { "Content-Type": "image/png" } })); vi.stubGlobal("fetch", upstream);
  const response = await GET(new NextRequest("http://localhost/api/assessments?student_id=other", { headers: { Authorization: "Bearer synthetic", "X-Role": "admin" } }), { params: Promise.resolve({ path: [id, "pages", "1", "image"] }) });
  expect(upstream).toHaveBeenCalledWith(`http://api:8000/v1/student/assessments/${id}/pages/1/image`, expect.objectContaining({ headers: { Authorization: "Bearer synthetic" }, cache: "no-store" }));
  expect(response.headers.get("Cache-Control")).toBe("no-store"); expect(await response.text()).toBe("synthetic png");
});
it("bounds declared upload size before contacting the API", async () => {
  const upstream = vi.fn(); vi.stubGlobal("fetch", upstream);
  const request = new NextRequest("http://localhost/api/assessments/upload", { method: "POST", headers: { Authorization: "Bearer synthetic", "Idempotency-Key": id, "Content-Type": "multipart/form-data; boundary=x", "Content-Length": "99999999" }, body: "synthetic" });
  expect((await POST(request, { params: Promise.resolve({ path: ["upload"] }) })).status).toBe(413); expect(upstream).not.toHaveBeenCalled();
});
