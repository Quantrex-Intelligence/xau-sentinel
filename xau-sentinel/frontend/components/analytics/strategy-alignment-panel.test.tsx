import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { StrategyAlignmentPanel } from "./strategy-alignment-panel";
import type { StrategyAnalytics } from "@/lib/types";

const { strategyAnalytics } = vi.hoisted(() => ({ strategyAnalytics: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { strategyAnalytics } }));

function analytics(overrides: Partial<StrategyAnalytics> = {}): StrategyAnalytics {
  return {
    overview: {
      total_trades: 10, wins: 6, losses: 3, breakeven: 1, win_rate: 60.0,
      total_r: 8.0, avg_r: 0.8, profit_factor: 2.1, median_r: 1.0, avg_holding_duration_minutes: 42.5,
      strategy_alignment_counts: { ALIGNED: 6, PARTIALLY_ALIGNED: 2, NOT_ALIGNED: 1, UNKNOWN: 1 },
      risk_alignment_counts: { ALIGNED: 8, PARTIALLY_ALIGNED: 1, NOT_ALIGNED: 0, UNKNOWN: 1 },
    },
    adherence: [
      { alignment: "ALIGNED", trade_count: 6, wins: 4, losses: 1, breakeven: 1, open: 0, unknown: 0 },
    ],
    ...overrides,
  };
}

describe("StrategyAlignmentPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders median R and avg holding duration", async () => {
    strategyAnalytics.mockResolvedValue(analytics());
    render(<StrategyAlignmentPanel />);
    await waitFor(() => expect(screen.getByText("+1R")).toBeInTheDocument());
    expect(screen.getByText("43 min")).toBeInTheDocument();
  });

  it("renders strategy and risk alignment counts", async () => {
    strategyAnalytics.mockResolvedValue(analytics());
    render(<StrategyAlignmentPanel />);
    await waitFor(() => expect(screen.getByText("ALIGNED: 6")).toBeInTheDocument());
    expect(screen.getByText("NOT ALIGNED: 0")).toBeInTheDocument();
  });

  it("renders the adherence vs. outcome table", async () => {
    strategyAnalytics.mockResolvedValue(analytics());
    render(<StrategyAlignmentPanel />);
    await waitFor(() => expect(screen.getByText("Adherence vs. Outcome")).toBeInTheDocument());
    expect(screen.getByText("Wins")).toBeInTheDocument();
  });

  it("shows an error state when the request fails", async () => {
    strategyAnalytics.mockRejectedValue(new Error("network down"));
    render(<StrategyAlignmentPanel />);
    await waitFor(() => expect(screen.getByText(/Unavailable/)).toBeInTheDocument());
  });

  it("never renders best/worst/winning-setup language or a numeric confidence score", async () => {
    strategyAnalytics.mockResolvedValue(analytics());
    render(<StrategyAlignmentPanel />);
    await waitFor(() => expect(screen.getByText("Adherence vs. Outcome")).toBeInTheDocument());
    const bodyText = document.body.textContent ?? "";
    const lowered = bodyText.toLowerCase();
    expect(lowered).not.toContain("best");
    expect(lowered).not.toContain("worst");
    expect(lowered).not.toContain("winning");
    expect(lowered).not.toContain("confidence");
  });
});
