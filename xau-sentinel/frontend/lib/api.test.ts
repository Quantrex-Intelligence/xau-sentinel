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

  it("posts chat messages to /api/ai/chat with a JSON body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        answer: "hi", conversation_id: "c1", context_used: [], sources: [],
        category: "INTERPRETATION", provider: "mock", model: "mock-deterministic-v1",
        created_at: "2026-01-01T00:00:00Z",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.aiChat({ message: "hello", conversation_id: "c1" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/ai/chat");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ message: "hello", conversation_id: "c1" });
    expect(result.answer).toBe("hi");
  });

  it("surfaces a 503 configuration error from /api/ai/chat as an ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        json: async () => ({ detail: "AI assistant not configured: AI_API_KEY is not set." }),
      })
    );
    await expect(api.aiChat({ message: "hello" })).rejects.toMatchObject(
      new ApiError(503, "AI assistant not configured: AI_API_KEY is not set.")
    );
  });

  it("fetches AI configuration status", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ configured: false, provider: "anthropic", model: null, reason: "AI_API_KEY is not set." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.aiConfig();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/ai/config");
    expect(result.configured).toBe(false);
  });
});
