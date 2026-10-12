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
it("preserves only validated dataset export options",async()=>{
  const fetch=vi.fn().mockResolvedValue(new Response('{"schema_version":1}\n',{headers:{"Content-Type":"application/x-ndjson"}}));vi.stubGlobal("fetch",fetch);vi.stubEnv("ADMIN_API_INTERNAL_URL","http://admin-api:8000");
  const context={params:Promise.resolve({path:["datasets",doc,"export"]})};
  const response=await GET(new NextRequest("http://localhost/api/studio?partition=holdout&preview=true",{headers:{Authorization:"Bearer synthetic"}}),context);
  expect(response.status).toBe(200);
  expect(fetch).toHaveBeenCalledWith(`http://admin-api:8000/v1/admin/studio/datasets/${doc}/export?partition=holdout&preview=true`,expect.anything());
  expect((await GET(new NextRequest("http://localhost/api/studio?partition=holdout&owner_id=forged",{headers:{Authorization:"Bearer synthetic"}}),context)).status).toBe(422);
  expect((await PATCH(new NextRequest("http://localhost/api/studio",{method:"PATCH",headers:{Authorization:"Bearer synthetic"}}),{params:Promise.resolve({path:["datasets",doc,"cases"]})})).status).toBe(404);
});
it("allows only scoped deletion and restore routes without requiring JSON bodies",async()=>{
  const {DELETE,POST}=await import("../app/api/studio/[[...path]]/route");
  const fetch=vi.fn().mockResolvedValue(new Response(null,{status:204}));vi.stubGlobal("fetch",fetch);
  expect((await DELETE(new NextRequest("http://localhost/api/studio",{method:"DELETE",headers:{Authorization:"Bearer synthetic"}}),{params:Promise.resolve({path:["sources",doc,"pages","2"]})})).status).toBe(204);
  expect((await POST(new NextRequest("http://localhost/api/studio",{method:"POST",headers:{Authorization:"Bearer synthetic"}}),{params:Promise.resolve({path:["sources",doc,"annotations",doc,"restore"]})})).status).toBe(204);
  expect((await DELETE(new NextRequest("http://localhost/api/studio",{method:"DELETE",headers:{Authorization:"Bearer synthetic"}}),{params:Promise.resolve({path:["datasets",doc]})})).status).toBe(404);
});
