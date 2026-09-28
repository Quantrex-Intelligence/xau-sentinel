import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MarketIntelligencePanel } from "./market-intelligence-panel";
import type { MarketIntelligenceContext } from "@/lib/types";

const { marketIntelligence } = vi.hoisted(() => ({ marketIntelligence: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { marketIntelligence } }));

const fullContext: MarketIntelligenceContext = {
  data_available: true,
  generated_at: "2026-01-01T00:00:00Z",
  macro: {
    data_available: true, source: "mock", generated_at: "2026-01-01T00:00:00Z",
    fed_funds_rate: 5.25, cpi_yoy: 3.0, core_cpi_yoy: 3.3, unemployment_rate: 4.0,
    gdp_growth_yoy: 2.1, us10y_yield: 4.2, us2y_yield: 4.5, reason: null, freshness: "MOCK",
  },
  gold_fundamentals: {
    data_available: true, source: "mock", generated_at: "2026-01-01T00:00:00Z",
    usd_strength_bias: "NEUTRAL", real_yield_10y: 1.2, central_bank_demand_trend: "ACCUMULATING",
    etf_flows_trend: "INFLOWS", reason: null, freshness: "MOCK",
  },
  cross_asset: {
    data_available: true, source: "mock", generated_at: "2026-01-01T00:00:00Z",
    dxy: 104.0, us2y_yield: 4.5, us10y_yield: 4.2, real_yield_10y: 1.2, vix: 15.0,
    equity_index: 5200.0, silver_price: 30.0, reason: null, freshness: "MOCK",
  },
  events: [{
    name: "[MOCK] US CPI (YoY)", category: "Inflation", importance: "HIGH",
    scheduled_at: "2026-01-02T13:30:00Z", source: "mock", actual: null, forecast: "3.0%", previous: "2.9%",
  }],
  news: [{
    id: "mock:1", headline: "[MOCK] Gold steadies as traders await Fed guidance", source: "mock-wire",
    published_at: "2026-01-01T00:00:00Z", retrieved_at: "2026-01-01T00:00:00Z", url: null,
    category: "macro", importance: "MEDIUM", assets: ["XAUUSD"], summary: "Offline mock summary.",
  }],
  sources: ["mock", "mock-wire"],
};

describe("MarketIntelligencePanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts collapsed", () => {
    marketIntelligence.mockResolvedValue(fullContext);
    render(<MarketIntelligencePanel />);
    expect(screen.getByText("Market intelligence")).toBeInTheDocument();
    expect(screen.queryByText("Macro")).not.toBeInTheDocument();
  });

  it("shows macro, gold fundamentals, cross-asset, events, and news once expanded", async () => {
    marketIntelligence.mockResolvedValue(fullContext);
    render(<MarketIntelligencePanel />);
    fireEvent.click(screen.getByText("Market intelligence"));

    await waitFor(() => expect(screen.getByText("Macro")).toBeInTheDocument());
    expect(screen.getByText("Gold Fundamentals")).toBeInTheDocument();
    expect(screen.getByText("Cross-Asset")).toBeInTheDocument();
    expect(screen.getByText("Economic Events")).toBeInTheDocument();
    expect(screen.getByText("News")).toBeInTheDocument();
    expect(screen.getByText("[MOCK] US CPI (YoY)")).toBeInTheDocument();
    expect(screen.getByText("[MOCK] Gold steadies as traders await Fed guidance")).toBeInTheDocument();
  });

  it("shows an error message when the request fails", async () => {
    marketIntelligence.mockRejectedValue(new Error("network down"));
    render(<MarketIntelligencePanel />);
    fireEvent.click(screen.getByText("Market intelligence"));
    await waitFor(() => expect(screen.getByText(/Unavailable/)).toBeInTheDocument());
  });

  it("never renders probability or win-forecast language", async () => {
    marketIntelligence.mockResolvedValue(fullContext);
    render(<MarketIntelligencePanel />);
    fireEvent.click(screen.getByText("Market intelligence"));
    await waitFor(() => expect(screen.getByText("Macro")).toBeInTheDocument());
    const bodyText = document.body.textContent ?? "";
    expect(bodyText.toLowerCase()).not.toContain("probability");
    expect(bodyText.toLowerCase()).not.toContain("chance of");
  });

  it("shows a MOCK freshness badge for mock-sourced sections", async () => {
    marketIntelligence.mockResolvedValue(fullContext);
    render(<MarketIntelligencePanel />);
    fireEvent.click(screen.getByText("Market intelligence"));
    await waitFor(() => expect(screen.getByText("Macro")).toBeInTheDocument());
    expect(screen.getAllByText("MOCK").length).toBeGreaterThanOrEqual(3);
  });

  it("shows a LIVE freshness badge and real data for a real, current section", async () => {
    marketIntelligence.mockResolvedValue({
      ...fullContext,
      macro: { ...fullContext.macro!, source: "real", freshness: "LIVE" },
    });
    render(<MarketIntelligencePanel />);
    fireEvent.click(screen.getByText("Market intelligence"));
    await waitFor(() => expect(screen.getByText("Macro")).toBeInTheDocument());
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(screen.getByText("real")).toBeInTheDocument();
  });

  it("shows an UNAVAILABLE badge and the reason when a real section has no data", async () => {
    marketIntelligence.mockResolvedValue({
      ...fullContext,
      macro: {
        data_available: false, source: "real", generated_at: null,
        fed_funds_rate: null, cpi_yoy: null, core_cpi_yoy: null, unemployment_rate: null,
        gdp_growth_yoy: null, us10y_yield: null, us2y_yield: null,
        reason: "MARKET_INTEL_FRED_API_KEY is not set — see .env.example.", freshness: "UNAVAILABLE",
      },
    });
    render(<MarketIntelligencePanel />);
    fireEvent.click(screen.getByText("Market intelligence"));
    await waitFor(() => expect(screen.getByText("Macro")).toBeInTheDocument());
    expect(screen.getByText("UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getByText("MARKET_INTEL_FRED_API_KEY is not set — see .env.example.")).toBeInTheDocument();
    expect(screen.queryByText("Fed Funds")).not.toBeInTheDocument();
  });

  it("shows a STALE badge for real data older than the freshness threshold", async () => {
    marketIntelligence.mockResolvedValue({
      ...fullContext,
      cross_asset: { ...fullContext.cross_asset!, source: "real", freshness: "STALE" },
    });
    render(<MarketIntelligencePanel />);
    fireEvent.click(screen.getByText("Market intelligence"));
    await waitFor(() => expect(screen.getByText("Cross-Asset")).toBeInTheDocument());
    expect(screen.getByText("STALE")).toBeInTheDocument();
  });
});
