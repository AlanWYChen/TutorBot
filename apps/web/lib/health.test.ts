import { afterEach, describe, expect, it, vi } from "vitest";
import { getApiHealth } from "./health";
afterEach(() => vi.unstubAllGlobals());
describe("API readiness", () => {
  it("reports a failed dependency check as unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 503 })));
    expect(await getApiHealth("http://api:8000")).toEqual({ status: "unavailable" });
  });
  it("handles a network failure without breaking the page", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    expect(await getApiHealth("http://api:8000")).toEqual({ status: "unavailable" });
  });
  it("reports successful readiness", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}")));
    expect(await getApiHealth("http://api:8000")).toEqual({ status: "ok" });
  });
});
