import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TradeDetailSheet } from "./trade-detail-sheet";
import type { Trade, TradeReview } from "@/lib/types";

const { trade, tradeReview, generateTradeReview } = vi.hoisted(() => ({
  trade: vi.fn(),
  tradeReview: vi.fn(),
  generateTradeReview: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  api: { trade, tradeReview, generateTradeReview },
  ApiError: class ApiError extends Error {},
}));

function closedTrade(overrides: Partial<Trade> = {}): Trade {
  return {
    id: 42, trade_date: "2026-01-01", trade_time: "10:00", symbol: "XAUUSD", direction: "BUY",
    session: "London", entry: 3700.0, stop_loss: 3690.0, take_profit: 3730.0, planned_rr: 3.0,
    setup: "liquidity sweep", market_regime: "TRENDING", notes: null, screenshot_path: null,
    exit_price: 3730.0, result: "WIN", pnl: 300.0, r_multiple: 3.0, duration_minutes: 45,
    exit_reason: null, rule_followed: null, mistake: null, exit_notes: null, status: "CLOSED",
    created_at: "2026-01-01T10:00:00Z", h4_bias: "BULLISH", h1_bias: "BULLISH", m15_bias: "BULLISH",
    m5_bias: "BULLISH", regime: "TRENDING", liquidity: "Previous Day Low swept", mss: "Bullish",
    displacement: "Bullish", fundednext_context: null,
    ...overrides,
  };
}

function review(overrides: Partial<TradeReview> = {}): TradeReview {
  return {
    trade_id: 42, outcome: "WIN", strategy_alignment: "ALIGNED", setup_alignment: "ALIGNED",
    execution_alignment: "ALIGNED", risk_alignment: "ALIGNED", deviations: [],
    rule_observations: ["H1 bias: consistent with BUY direction."], r_multiple: 3.0,
    holding_duration_minutes: 45, similar_trade_context: "", behavioral_context: [],
    knowledge_context: [], memory_context: [], uncertainties: [], interpretation: null,
    sources: [], reviewed_at: "2026-01-01T10:05:00Z", llm_provider: null, llm_model: null, llm_error: null,
    ...overrides,
  };
}

describe("TradeDetailSheet", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders trade facts once fetched", async () => {
    trade.mockResolvedValue(closedTrade());
    render(<TradeDetailSheet tradeId={42} onOpenChange={() => {}} onClosed={() => {}} />);
    await screen.findByText("Trade #42 —");
    expect(screen.getByText("WIN")).toBeInTheDocument();
  });

  it("shows a Review Trade action for a closed trade", async () => {
    trade.mockResolvedValue(closedTrade());
    render(<TradeDetailSheet tradeId={42} onOpenChange={() => {}} onClosed={() => {}} />);
    await screen.findByText("Review Trade");
  });

  it("does not show Review Trade for an open trade", async () => {
    trade.mockResolvedValue(closedTrade({ status: "OPEN", result: null, exit_price: null }));
    render(<TradeDetailSheet tradeId={42} onOpenChange={() => {}} onClosed={() => {}} />);
    await screen.findByText("CLOSE THIS TRADE");
    expect(screen.queryByText("Review Trade")).not.toBeInTheDocument();
  });

  it("clicking Review Trade fetches and renders the deterministic review", async () => {
    trade.mockResolvedValue(closedTrade());
    tradeReview.mockResolvedValue(review());
    render(<TradeDetailSheet tradeId={42} onOpenChange={() => {}} onClosed={() => {}} />);
    fireEvent.click(await screen.findByText("Review Trade"));

    await waitFor(() => expect(tradeReview).toHaveBeenCalledWith(42));
    expect(await screen.findByText("Strategy alignment")).toBeInTheDocument();
    expect(screen.getAllByText("ALIGNED").length).toBeGreaterThan(0);
    expect(screen.getByText("H1 bias: consistent with BUY direction.")).toBeInTheDocument();
  });

  it("shows deviations when present", async () => {
    trade.mockResolvedValue(closedTrade());
    tradeReview.mockResolvedValue(review({
      strategy_alignment: "NOT_ALIGNED", setup_alignment: "NOT_ALIGNED",
      deviations: [{ type: "DIRECTION_DEVIATION", evidence: "Recorded H1 bias contradicts direction." }],
    }));
    render(<TradeDetailSheet tradeId={42} onOpenChange={() => {}} onClosed={() => {}} />);
    fireEvent.click(await screen.findByText("Review Trade"));

    expect(await screen.findByText("Recorded H1 bias contradicts direction.")).toBeInTheDocument();
    expect(screen.getAllByText("NOT ALIGNED").length).toBe(2); // strategy + setup both NOT_ALIGNED
  });

  it("shows a Generate AI review action when interpretation is not yet cached", async () => {
    trade.mockResolvedValue(closedTrade());
    tradeReview.mockResolvedValue(review({ interpretation: null }));
    render(<TradeDetailSheet tradeId={42} onOpenChange={() => {}} onClosed={() => {}} />);
    fireEvent.click(await screen.findByText("Review Trade"));

    expect(await screen.findByText("Generate AI review")).toBeInTheDocument();
  });

  it("clicking Generate AI review calls generateTradeReview and renders the interpretation", async () => {
    trade.mockResolvedValue(closedTrade());
    tradeReview.mockResolvedValue(review({ interpretation: null }));
    generateTradeReview.mockResolvedValue(review({
      interpretation: "The trade followed the recorded H1 bias and MSS confirmation.",
    }));
    render(<TradeDetailSheet tradeId={42} onOpenChange={() => {}} onClosed={() => {}} />);
    fireEvent.click(await screen.findByText("Review Trade"));
    fireEvent.click(await screen.findByText("Generate AI review"));

    await waitFor(() => expect(generateTradeReview).toHaveBeenCalledWith(42));
    expect(await screen.findByText("The trade followed the recorded H1 bias and MSS confirmation.")).toBeInTheDocument();
  });

  it("shows a safe fallback when the review fetch fails", async () => {
    trade.mockResolvedValue(closedTrade());
    tradeReview.mockRejectedValue(new Error("network error"));
    render(<TradeDetailSheet tradeId={42} onOpenChange={() => {}} onClosed={() => {}} />);
    fireEvent.click(await screen.findByText("Review Trade"));

    expect(await screen.findByText("Review unavailable.")).toBeInTheDocument();
  });

  it("still renders the Explain with AI link (Stage 3/6 chat deep-link, unaffected)", async () => {
    trade.mockResolvedValue(closedTrade());
    render(<TradeDetailSheet tradeId={42} onOpenChange={() => {}} onClosed={() => {}} />);
    await screen.findByText("Explain with AI");
  });

  it("never renders probability or win-forecast language", async () => {
    trade.mockResolvedValue(closedTrade());
    tradeReview.mockResolvedValue(review({
      interpretation: "The trade followed the recorded H1 bias and MSS confirmation.",
    }));
    render(<TradeDetailSheet tradeId={42} onOpenChange={() => {}} onClosed={() => {}} />);
    fireEvent.click(await screen.findByText("Review Trade"));
    await screen.findByText(/followed the recorded H1 bias/);

    const bodyText = document.body.textContent ?? "";
    expect(bodyText.toLowerCase()).not.toContain("probability");
    expect(bodyText.toLowerCase()).not.toContain("chance of");
  });
});
