import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnalysisView } from "./analysis-view";
import { utcClock } from "./shared";
import type { AnalysisV2Response } from "@/lib/types";

const TIMEFRAME_STATE = (tf: string, state: string) => ({
  timeframe: tf,
  state,
  reason: `${tf} reason`,
  last_bos: null,
  last_mss: null,
  last_high: 4141.7,
  last_low: 4125.1,
  last_high_label: "HH",
  last_low_label: "HL",
});

function response(overrides: Partial<AnalysisV2Response> = {}): AnalysisV2Response {
  const base: AnalysisV2Response = {
    status: "OK",
    status_reason: "Closed M5 history and a current price are available.",
    freshness: {
      generated_at_utc: "2026-10-05T10:00:00+00:00",
      as_of_utc: "2026-10-05T09:55:00+00:00",
      m5_bar_close_utc: "2026-10-05T10:00:00+00:00",
      age_seconds: 300,
      threshold_seconds: 420,
      stale: false,
    },
    source: {
      provider: "MT5 live",
      mode: "live",
      symbol: "XAUUSDm",
      server_timezone: "UTC",
      timeframes: {},
    },
    notes: [],
    data_issues: [],
    facts: {
      observations: {
        current_price: 4140.31,
        atr_m5: 3.03,
        atr_h1: 9.1,
        atr_percentile_m5: 40,
        atr_change_m5: 0.9,
        range_ratio_m5: 1.1,
        displacement_m5: null,
        volume_m5: { relative_volume: 0.66, volume_percentile: 30, state: "CONTRACTION" },
        session: "New York",
        zones: {},
        zone_distances_atr: {},
        recent_high: 4150,
        recent_low: 4125,
        sweeps: [],
        equal_levels: [],
      },
      structure: {
        H4: TIMEFRAME_STATE("H4", "RANGING"),
        H1: TIMEFRAME_STATE("H1", "RANGING"),
        M15: TIMEFRAME_STATE("M15", "BULLISH"),
        M5: TIMEFRAME_STATE("M5", "BEARISH"),
      },
    },
    events: [
      {
        kind: "SWEEP",
        timeframe: "M5",
        time_utc: "2026-10-05T09:50:00+00:00",
        direction: "bullish",
        price: 4125.1,
        detail: "Previous Day Low swept; M5 closed back above it",
      },
    ],
    interpretation: {
      context: {
        direction: { state: "NONE", detail: "H1 and H4 are ranging." },
        structure: {},
        regime: { state: "RANGING", detail: "Lower high but higher low." },
        volatility: { state: "LOW", detail: "ATR at the 40th percentile." },
        volume: { state: "CONTRACTION", detail: "Tick volume is an activity proxy." },
        liquidity: { state: "SWEPT_LOW", detail: "Previous Day Low swept." },
        momentum: { state: "STEADY", detail: "Recent bodies similar." },
        session: { state: "New York", detail: "Configured UTC window." },
        price_location: { state: "MIDDLE_THIRD", detail: "Price at 40% of the day range." },
      },
      key_areas: [
        {
          low: 4139.07,
          high: 4140.28,
          side: "SUPPORT",
          strength_status: "MODERATE",
          strength_reason: "2 kinds",
          relation: "APPROACHING",
          distance_atr: 0.03,
          reasons: ["Price is 0.03 ATR from the nearest edge of the area."],
          components: [
            { label: "H1 swing low", price: 4139.07, timeframe: "H1", kind: "H1_SWING_LOW", source: "analysis.structure", note: "" },
          ],
          events: [],
        },
      ],
      confluence: {
        reference: null,
        reference_reason: "No clear trend on H1 or H4.",
        supporting: [],
        contradicting: [],
        neutral: [{ source: "volume", timeframe: "M5", lean: "neutral", detail: "Activity only." }],
        bullish: [],
        bearish: [],
        cross_timeframe_conflicts: ["M15 BULLISH vs M5 BEARISH"],
      },
      narrative: ["Direction: H1 and H4 are ranging.", "Structure: H4 ranging, H1 ranging, M15 bullish, M5 bearish."],
    },
    scenarios: [
      {
        name: "RANGE",
        direction: null,
        condition: "While price stays within 4125.10-4141.70, the market is treated as two-sided.",
        supporting_conditions: [],
        confirmation_requirements: ["A rejection of either edge on M5 before a directional break"],
        invalidation_conditions: ["M5 closes beyond an edge with a displacement bar"],
        key_area_refs: [],
        event_refs: [],
        disclaimer: "Conditional scenarios describe what would need to happen. They are not predictions and not trade signals.",
      },
    ],
  };
  return { ...base, ...overrides };
}

const FORBIDDEN = /probab|confiden|\bBUY\b|\bSELL\b|win rate|\bscore\b/i;

describe("AnalysisView", () => {
  it("shows the sections in the priority order a reader needs", () => {
    const { container } = render(<AnalysisView data={response()} error={null} loading={false} />);
    const headings = Array.from(container.querySelectorAll("h3")).map((h) => h.textContent ?? "");
    const order = [
      "Market overview",
      "Multi-timeframe structure",
      "Key areas",
      "Recent events",
      "Market context",
      "Confluence and contradictions",
      "Narrative",
      "Conditional scenarios",
    ];
    const positions = order.map((title) => headings.findIndex((h) => h.includes(title)));
    positions.forEach((p) => expect(p).toBeGreaterThanOrEqual(0));
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });

  it("labels each section as observed, interpreted or conditional", () => {
    render(<AnalysisView data={response()} error={null} loading={false} />);
    expect(screen.getAllByText("Observed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Interpreted").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Conditional").length).toBeGreaterThan(0);
  });

  it("renders scenarios with confirmation, invalidation and the disclaimer", () => {
    render(<AnalysisView data={response()} error={null} loading={false} />);
    expect(screen.getByText("Confirmation requires")).toBeInTheDocument();
    expect(screen.getByText("Invalidated if")).toBeInTheDocument();
    expect(screen.getByText(/not predictions and not trade signals/)).toBeInTheDocument();
  });

  it("shows a stale banner with the explanation and the age of the last closed bar", () => {
    const stale = response({
      status: "STALE",
      status_reason: "The M5 feed is older than the staleness window; the analysis describes history, not now.",
      notes: ["The M5 feed is older than the configured staleness window; read the analysis as historical."],
      freshness: { ...response().freshness, stale: true, age_seconds: 172800 },
    });
    render(<AnalysisView data={stale} error={null} loading={false} />);
    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.getByText(/read the analysis as historical/)).toBeInTheDocument();
    expect(screen.getByText(/Age: 2880 min/)).toBeInTheDocument();
  });

  it("explains an unavailable MT5 connection and shows no estimated market content", () => {
    const down = response({
      status: "UNAVAILABLE",
      status_reason: "MT5 data is unavailable: MT5 not connected",
      facts: { observations: null, structure: {} },
      interpretation: { context: null, key_areas: [], confluence: null, narrative: [] },
      events: [],
      scenarios: [],
    });
    render(<AnalysisView data={down} error={null} loading={false} />);
    expect(screen.getByText("MT5 unavailable")).toBeInTheDocument();
    expect(screen.getByText("No market data")).toBeInTheDocument();
    expect(screen.queryByText("Market overview")).not.toBeInTheDocument();
    expect(screen.queryByText("Conditional scenarios")).not.toBeInTheDocument();
  });

  it("lists insufficient-data reasons under data limits", () => {
    const thin = response({
      status: "INSUFFICIENT_DATA",
      status_reason: "Not enough closed market data for a read: H1: insufficient closed history (34 bars, need 60).",
      data_issues: ["H1: insufficient closed history (34 bars, need 60)"],
    });
    render(<AnalysisView data={thin} error={null} loading={false} />);
    expect(screen.getByText("Data limits")).toBeInTheDocument();
    expect(screen.getAllByText(/insufficient closed history/).length).toBeGreaterThan(0);
  });

  it("marks mock data as synthetic so it is never mistaken for market data", () => {
    const mock = response({
      source: { ...response().source, provider: "MOCK (synthetic, not market data)", mode: "mock" },
    });
    render(<AnalysisView data={mock} error={null} loading={false} />);
    expect(screen.getByText("Synthetic test data is shown. It is not market data.")).toBeInTheDocument();
  });

  it("shows a read-only footnote for live data", () => {
    render(<AnalysisView data={response()} error={null} loading={false} />);
    expect(screen.getByText(/Read-only\. This view never places, closes, or modifies orders\./)).toBeInTheDocument();
  });

  it("shows loading and error states without a crash", () => {
    const { rerender } = render(<AnalysisView data={null} error={null} loading />);
    expect(screen.getByText("Loading analysis")).toBeInTheDocument();
    rerender(<AnalysisView data={null} error={new Error("boom")} loading={false} />);
    expect(screen.getByText(/could not be loaded: boom/)).toBeInTheDocument();
  });

  it("never shows probabilities, confidence, buy/sell calls or scores", () => {
    const { container } = render(<AnalysisView data={response()} error={null} loading={false} />);
    const hit = (container.textContent ?? "").match(new RegExp(".{0,30}(" + FORBIDDEN.source + ").{0,30}", "i"));
    expect(hit ? hit[0] : null).toBeNull();
  });

  it("states that distances are measured from the last closed price", () => {
    render(<AnalysisView data={response()} error={null} loading={false} />);
    expect(screen.getByText(/measured from the last closed M5 price 4,?140\.31/)).toBeInTheDocument();
  });
});

describe("utcClock", () => {
  it("formats an ISO timestamp as HH:MM UTC", () => {
    expect(utcClock("2026-10-05T09:50:00+00:00")).toBe("09:50 UTC");
  });

  it("returns a dash for missing or invalid times rather than inventing one", () => {
    expect(utcClock(null)).toBe("—");
    expect(utcClock("not a date")).toBe("—");
  });
});
