export function GET() {
  const local = process.env.APP_ENV === "local";
  const projectId = process.env.FIREBASE_PROJECT_ID;
  const apiKey = process.env.FIREBASE_WEB_API_KEY;
  if (!projectId || !apiKey || (local && !projectId.startsWith("demo-"))) {
    return Response.json({ detail: "Sign-in unavailable" }, { status: 503 });
  }
  return Response.json({ projectId, apiKey, emulatorUrl: local ? "http://localhost:9099" : null }, { headers: { "Cache-Control": "no-store" } });
}
