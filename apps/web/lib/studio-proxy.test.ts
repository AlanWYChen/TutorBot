import { afterEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, PATCH } from "../app/api/studio/[[...path]]/route";
const doc="12345678-1234-1234-1234-123456789abc";
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();});
it("denies arbitrary destinations and anonymous annotation crops", async()=>{
  const fetch=vi.fn();vi.stubGlobal("fetch",fetch);
  expect((await GET(new NextRequest("http://localhost/api/studio"),{params:Promise.resolve({path:["student","account"]})})).status).toBe(404);
  expect((await GET(new NextRequest("http://localhost/api/studio"),{params:Promise.resolve({path:["sources",doc,"annotations",doc,"crop"]})})).status).toBe(401);
  expect(fetch).not.toHaveBeenCalled();
});
it("sends edits only to fixed maintainer API paths without client scope headers",async()=>{
  vi.stubEnv("ADMIN_API_INTERNAL_URL","http://admin-api:8000");
  const fetch=vi.fn().mockResolvedValue(Response.json({revision:2}));vi.stubGlobal("fetch",fetch);
  const response=await PATCH(new NextRequest("http://localhost/api/studio?student_id=forged",{method:"PATCH",headers:{Authorization:"Bearer synthetic","Content-Type":"application/json","X-Role":"admin"},body:'{"expected_revision":1}'}),{params:Promise.resolve({path:["sources",doc,"annotations",doc]})});
  expect(response.status).toBe(200);expect(response.headers.get("Cache-Control")).toBe("no-store");
  expect(fetch).toHaveBeenCalledWith(`http://admin-api:8000/v1/admin/studio/sources/${doc}/annotations/${doc}`,expect.objectContaining({method:"PATCH",headers:{Authorization:"Bearer synthetic","Content-Type":"application/json"}}));
});
