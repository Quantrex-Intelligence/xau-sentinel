import { describe, expect, it } from "vitest";
import { formatPrice, formatR, formatAgo } from "./format";

describe("formatPrice", () => {
  it("formats with 2 decimals by default", () => {
    expect(formatPrice(3741.5)).toBe("3,741.50");
  });
  it("returns an em dash for null/undefined", () => {
    expect(formatPrice(null)).toBe("—");
    expect(formatPrice(undefined)).toBe("—");
  });
  it("respects a custom digit count", () => {
    expect(formatPrice(3741.123, 3)).toBe("3,741.123");
  });
});

describe("formatR", () => {
  it("prefixes positive values with +", () => {
    expect(formatR(2)).toBe("+2.00R");
  });
  it("does not prefix negative values", () => {
    expect(formatR(-1.5)).toBe("-1.50R");
  });
  it("treats zero as non-negative (+0.00R, matching the Risk panel's convention)", () => {
    expect(formatR(0)).toBe("+0.00R");
  });
  it("returns an em dash for null/undefined", () => {
    expect(formatR(null)).toBe("—");
  });
});

describe("formatAgo", () => {
  it("returns an em dash for null/undefined", () => {
    expect(formatAgo(null)).toBe("—");
    expect(formatAgo(undefined)).toBe("—");
  });
  it("formats a recent timestamp in seconds", () => {
    const tenSecondsAgo = Math.floor(Date.now() / 1000) - 10;
    expect(formatAgo(tenSecondsAgo)).toMatch(/^\d+s ago$/);
  });
  it("formats an older timestamp in minutes", () => {
    const fiveMinutesAgo = Math.floor(Date.now() / 1000) - 5 * 60;
    expect(formatAgo(fiveMinutesAgo)).toMatch(/^\d+m ago$/);
  });
});
