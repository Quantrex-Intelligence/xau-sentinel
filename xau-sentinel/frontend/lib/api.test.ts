import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";

describe("api client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("parses a successful JSON response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok" }),
      })
    );
    const result = await api.health();
    expect(result).toEqual({ status: "ok" });
  });

  it("throws ApiError with the backend's detail message on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        json: async () => ({ detail: "MT5 not connected" }),
      })
    );
    await expect(api.ticker()).rejects.toMatchObject(
      new ApiError(503, "MT5 not connected")
    );
  });

  it("falls back to statusText when the error body isn't JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => {
          throw new Error("not json");
        },
      })
    );
    await expect(api.ticker()).rejects.toMatchObject(
      new ApiError(500, "Internal Server Error")
    );
  });

  it("builds query strings for filtered trade requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);
    await api.trades({ direction: "BUY" });
    const calledUrl = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toContain("/api/journal/trades?direction=BUY");
  });

  it("sends candle requests with the requested timeframe and count", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);
    await api.candles("H1", 100);
    const calledUrl = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toContain("timeframe=H1");
    expect(calledUrl).toContain("count=100");
  });
});
