import { describe, expect, it } from "vitest";
import { detectConflict } from "./market-conflict";
import type { AnalysisV2Response, EntryModelResult } from "./types";

function v2(direction: "UP" | "DOWN" | "NONE" | null): AnalysisV2Response {
  return {
    interpretation: {
      context: direction === null ? null : {
        direction: { state: direction, detail: "" },
        structure: {}, regime: { state: "", detail: "" }, volatility: { state: "", detail: "" },
        volume: { state: "", detail: "" }, liquidity: { state: "", detail: "" },
        momentum: { state: "", detail: "" }, session: { state: "", detail: "" },
        price_location: { state: "", detail: "" }, trend_strength: { state: "", detail: "" },
      },
    },
  } as unknown as AnalysisV2Response;
}

function entry(overrides: Partial<EntryModelResult>): EntryModelResult {
  return {
    symbol: "XAUUSD", direction: null, state: "NO_CONTEXT", as_of: null, disclaimer: "",
    higher_timeframe: null, intraday: null, setup_15m: null, confirmation_5m: null,
    precision_1m: null, entry_candidate: null, confidence: null,
    supporting_evidence: [], contradicting_evidence: [], invalidation: null, next_condition: null,
    ...overrides,
  };
}

describe("detectConflict", () => {
  it("reports nothing when market context has not resolved yet", () => {
    expect(detectConflict(v2(null), entry({ state: "ENTRY_READY", direction: "LONG" }))).toBeNull();
    expect(detectConflict(v2("NONE"), entry({ state: "ENTRY_READY", direction: "LONG" }))).toBeNull();
  });

  it("reports nothing when the Entry Model has no data yet", () => {
    expect(detectConflict(v2("UP"), null)).toBeNull();
  });

  it("reports nothing when the Entry Model direction has not resolved yet (still developing)", () => {
    expect(detectConflict(v2("UP"), entry({ state: "SETUP_DEVELOPING", direction: null }))).toBeNull();
  });

  it("reports nothing when both engines genuinely agree", () => {
    expect(detectConflict(v2("UP"), entry({ state: "ENTRY_READY", direction: "LONG" }))).toBeNull();
    expect(detectConflict(v2("DOWN"), entry({ state: "ENTRY_READY", direction: "SHORT" }))).toBeNull();
  });

  it("flags a genuine conflict when Entry Model is CONFLICTED while market context has a side", () => {
    const result = detectConflict(
      v2("UP"),
      entry({
        state: "CONFLICTED", direction: "CONFLICTED",
        higher_timeframe: { htf_context: "BULLISH" } as EntryModelResult["higher_timeframe"],
        intraday: { intraday_bias: "BEARISH" } as EntryModelResult["intraday"],
      }),
    );
    expect(result).toEqual({
      marketContext: "Bullish", entryModel: "CONFLICTED",
      reason: "1H bias (bearish) conflicts with the established 1D/4H context (bullish).",
    });
  });

  it("flags a genuine conflict when Entry Model resolved the opposite direction from market context", () => {
    const result = detectConflict(v2("DOWN"), entry({ state: "ENTRY_READY", direction: "LONG" }));
    expect(result).toEqual({
      marketContext: "Bearish", entryModel: "LONG",
      reason: "Entry Model's confirmed LONG direction is opposite the established market context (Bearish).",
    });
  });

  it("falls back to a generic reason when no specific rung mismatch can be named", () => {
    const result = detectConflict(v2("UP"), entry({ state: "CONFLICTED", direction: "CONFLICTED" }));
    expect(result?.reason).toBe("Entry Model's own evidence is split between LONG and SHORT.");
  });
});
