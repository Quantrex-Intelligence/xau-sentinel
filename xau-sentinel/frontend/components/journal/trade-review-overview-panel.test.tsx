import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { TradeReviewOverviewPanel } from "./trade-review-overview-panel";
import type { TradeReviewSummary } from "@/lib/types";

const { tradeReviewSummary } = vi.hoisted(() => ({ tradeReviewSummary: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { tradeReviewSummary } }));

function summary(overrides: Partial<TradeReviewSummary> = {}): TradeReviewSummary {
  return {
    trades_reviewed: 10, strategy_aligned: 6, partially_aligned: 2, not_aligned: 1, unknown: 1,
    patterns: [], insufficient_sample_note: null,
    ...overrides,
  };
}

describe("TradeReviewOverviewPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders alignment counts from the summary", async () => {
    tradeReviewSummary.mockResolvedValue(summary());
    render(<TradeReviewOverviewPanel />);
    await waitFor(() => expect(screen.getByText("10")).toBeInTheDocument());
    expect(screen.getByText("6")).toBeInTheDocument();
  });

  it("shows the insufficient-sample note when the sample is too small", async () => {
    tradeReviewSummary.mockResolvedValue(summary({
      trades_reviewed: 1, strategy_aligned: 1, partially_aligned: 0, not_aligned: 0, unknown: 0,
      insufficient_sample_note: "Insufficient historical sample for a meaningful recurring-pattern conclusion.",
    }));
    render(<TradeReviewOverviewPanel />);
    await waitFor(() => expect(screen.getByText(/Insufficient historical sample/)).toBeInTheDocument());
  });

  it("renders recurring patterns with sample counts, never a bare percentage claim of causation", async () => {
    tradeReviewSummary.mockResolvedValue(summary({
      patterns: [{
        deviation_type: "DIRECTION_DEVIATION", sample_count: 6, total_relevant_trades: 84,
        occurrence_rate: 0.0714, trades_with_loss: 4, note: "Observed historical association, not evidence of causation.",
      }],
    }));
    render(<TradeReviewOverviewPanel />);
    await waitFor(() => expect(screen.getByText("DIRECTION DEVIATION")).toBeInTheDocument());
    expect(screen.getByText("6 / 84 (7.1%)")).toBeInTheDocument();
    expect(screen.getByText(/not evidence of causation/)).toBeInTheDocument();
  });

  it("shows no-patterns state when the list is empty and sample is sufficient", async () => {
    tradeReviewSummary.mockResolvedValue(summary({ patterns: [], insufficient_sample_note: null }));
    render(<TradeReviewOverviewPanel />);
    await waitFor(() => expect(screen.getByText("No recurring patterns observed.")).toBeInTheDocument());
  });

  it("shows an error state when the request fails", async () => {
    tradeReviewSummary.mockRejectedValue(new Error("network down"));
    render(<TradeReviewOverviewPanel />);
    await waitFor(() => expect(screen.getByText(/Unavailable/)).toBeInTheDocument());
  });

  it("never renders a numeric confidence score or a causal claim", async () => {
    tradeReviewSummary.mockResolvedValue(summary({
      patterns: [{
        deviation_type: "RISK_LIMIT_DEVIATION", sample_count: 4, total_relevant_trades: 20,
        occurrence_rate: 0.2, trades_with_loss: 3, note: "Observed historical association, not evidence of causation.",
      }],
    }));
    render(<TradeReviewOverviewPanel />);
    await waitFor(() => expect(screen.getByText("RISK LIMIT DEVIATION")).toBeInTheDocument());
    const bodyText = document.body.textContent ?? "";
    expect(bodyText.toLowerCase()).not.toContain("confidence");
    expect(bodyText.toLowerCase()).not.toMatch(/\bcauses?\b/);
  });
});
