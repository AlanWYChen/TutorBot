import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "../app/api/auth/[...path]/route";

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
describe("fixed authentication proxy", () => {
  it("rejects unsupported paths before contacting the API", async () => {
    const upstream = vi.fn(); vi.stubGlobal("fetch", upstream);
    for (const path of [["constructor"], ["https:", "evil.invalid"], ["admin", "publish"]]) {
      const response = await GET(new NextRequest("http://localhost/api/auth/test"), { params: Promise.resolve({ path }) });
      expect(response.status).toBe(404);
    }
    expect(upstream).not.toHaveBeenCalled();
  });
  it("rejects missing authentication before contacting the API", async () => {
    const upstream = vi.fn(); vi.stubGlobal("fetch", upstream);
    const response = await GET(new NextRequest("http://localhost/api/auth/me"), { params: Promise.resolve({ path: ["me"] }) });
    expect(response.status).toBe(401); expect(upstream).not.toHaveBeenCalled();
  });
  it("forwards only the bearer token to a fixed route and disables caching", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const upstream = vi.fn().mockResolvedValue(Response.json({ role: "student" })); vi.stubGlobal("fetch", upstream);
    const response = await GET(new NextRequest("http://localhost/api/auth/me?student_id=other", { headers: { authorization: "Bearer synthetic-token", "X-Role": "admin" } }), { params: Promise.resolve({ path: ["me"] }) });
    expect(upstream).toHaveBeenCalledWith("http://api:8000/v1/auth/me", expect.objectContaining({ headers: { Authorization: "Bearer synthetic-token" }, cache: "no-store" }));
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(await response.json()).toEqual({ role: "student" });
  });
});

it("routes maintainer activity to the separate admin service", async () => {
  vi.stubEnv("ADMIN_API_INTERNAL_URL", "http://admin-api:8000");
  const upstream = vi.fn().mockResolvedValue(Response.json([])); vi.stubGlobal("fetch", upstream);
  await GET(new NextRequest("http://localhost/api/auth/audit", { headers: { authorization: "Bearer synthetic-token" } }), { params: Promise.resolve({ path: ["audit"] }) });
  expect(upstream).toHaveBeenCalledWith("http://admin-api:8000/v1/admin/audit", expect.objectContaining({ cache: "no-store" }));
});
