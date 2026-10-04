import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("analysisV2 client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("issues a single GET to the read-only V2 endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "OK" }) });
    vi.stubGlobal("fetch", fetchMock);
    const result = await api.analysisV2();
    expect(result).toEqual({ status: "OK" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/analysis\/v2$/);
    expect((init as RequestInit | undefined)?.method ?? "GET").toBe("GET");
  });
});
