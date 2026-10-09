import { describe, expect, it } from "vitest";
import { formatBarDateTime, isAtLiveEdge, WITHIN_BARS_OF_LIVE } from "./candlestick-chart";
import type { UTCTimestamp } from "lightweight-charts";

describe("formatBarDateTime", () => {
  it("reads the UTC wall-clock time, not the local timezone", () => {
    const t = Date.UTC(2026, 9, 8, 14, 35) / 1000; // 2026-10-08T14:35:00Z
    const text = formatBarDateTime(t as UTCTimestamp);
    expect(text).toContain("14:35");
    expect(text).toContain("UTC");
    expect(text).toContain("Oct");
    expect(text).toContain("08");
  });

  it("includes the date, not just the time, since the OHLC legend spans many days", () => {
    const t = Date.UTC(2026, 0, 2, 0, 5) / 1000; // 2026-01-02T00:05:00Z
    const text = formatBarDateTime(t as UTCTimestamp);
    expect(text).toContain("Jan");
    expect(text).toContain("02");
    expect(text).toContain("00:05");
  });
});

describe("isAtLiveEdge", () => {
  it("is true when the visible range's right edge is exactly the last bar", () => {
    expect(isAtLiveEdge(299, 300)).toBe(true);
  });

  it(`is true within ${WITHIN_BARS_OF_LIVE} bars of the edge, not just an exact match`, () => {
    expect(isAtLiveEdge(298, 300)).toBe(true);
  });

  it("is false once scrolled further back than the tolerance", () => {
    expect(isAtLiveEdge(100, 300)).toBe(false);
  });

  it("is true when the visible range extends past the last bar (panned slightly into empty space)", () => {
    expect(isAtLiveEdge(310, 300)).toBe(true);
  });
});
