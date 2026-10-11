export type ServiceHealth = { status: "ok" | "unavailable" };
export async function getApiHealth(baseUrl: string): Promise<ServiceHealth> {
  try {
    const response = await fetch(`${baseUrl}/health/ready`, { cache: "no-store", signal: AbortSignal.timeout(5000) });
    return { status: response.ok ? "ok" : "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}
