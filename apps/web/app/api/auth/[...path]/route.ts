import { NextRequest } from "next/server";

// Fixed routes: never proxy arbitrary URLs, headers, student IDs, or admin actions.
const routes = new Map([["me", "/v1/auth/me"], ["account", "/v1/student/account"], ["maintainer", "/v1/admin/access"], ["audit", "/v1/admin/audit"]]);
export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = routes.get(path.join("/"));
  if (!target) return Response.json({ detail: "Not found" }, { status: 404 });
  const authorization = request.headers.get("authorization");
  if (!authorization) return Response.json({ detail: "Sign-in required" }, { status: 401 });
  try {
    const origin = target.startsWith("/v1/admin/")
      ? process.env.ADMIN_API_INTERNAL_URL ?? "http://localhost:8001"
      : process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const response = await fetch(`${origin}${target}`, {
      headers: { Authorization: authorization }, cache: "no-store", signal: AbortSignal.timeout(10000),
    });
    return new Response(await response.text(), { status: response.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ detail: "Service unavailable" }, { status: 503 });
  }
}
