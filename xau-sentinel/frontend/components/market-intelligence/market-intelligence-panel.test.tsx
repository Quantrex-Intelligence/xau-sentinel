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
    gdp_growth_yoy: 2.1, us10y_yield: 4.2, us2y_yield: 4.5, reason: null,
  },
  gold_fundamentals: {
    data_available: true, source: "mock", generated_at: "2026-01-01T00:00:00Z",
    usd_strength_bias: "NEUTRAL", real_yield_10y: 1.2, central_bank_demand_trend: "ACCUMULATING",
    etf_flows_trend: "INFLOWS", reason: null,
  },
  cross_asset: {
    data_available: true, source: "mock", generated_at: "2026-01-01T00:00:00Z",
    dxy: 104.0, us2y_yield: 4.5, us10y_yield: 4.2, real_yield_10y: 1.2, vix: 15.0,
    equity_index: 5200.0, silver_price: 30.0, reason: null,
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
});
