import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DimensionBreakdownPanel } from "./dimension-breakdown-panel";
import type { DimensionBreakdown } from "@/lib/types";

const { strategyAnalyticsDimension } = vi.hoisted(() => ({ strategyAnalyticsDimension: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { strategyAnalyticsDimension } }));

function breakdown(dimension: string, rows: DimensionBreakdown["rows"]): DimensionBreakdown {
  return { dimension, rows };
}

describe("DimensionBreakdownPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches the direction breakdown by default and renders rows", async () => {
    strategyAnalyticsDimension.mockResolvedValue(breakdown("direction", [
      { value: "BUY", sample_size: 8, wins: 5, losses: 3, breakeven: 0, win_rate: 62.5, avg_r: 0.5, total_r: 4.0, insufficient_sample: false },
    ]));
    render(<DimensionBreakdownPanel />);
    await waitFor(() => expect(strategyAnalyticsDimension).toHaveBeenCalledWith("direction"));
    expect(await screen.findByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("62.5%")).toBeInTheDocument();
  });

  it("refetches when a different dimension is selected", async () => {
    strategyAnalyticsDimension.mockResolvedValue(breakdown("direction", []));
    render(<DimensionBreakdownPanel />);
    await waitFor(() => expect(strategyAnalyticsDimension).toHaveBeenCalledWith("direction"));

    strategyAnalyticsDimension.mockResolvedValue(breakdown("regime", [
      { value: "TRENDING", sample_size: 4, wins: 2, losses: 2, breakeven: 0, win_rate: 50.0, avg_r: 0.1, total_r: 0.4, insufficient_sample: false },
    ]));
    fireEvent.click(screen.getByText("Regime"));
    await waitFor(() => expect(strategyAnalyticsDimension).toHaveBeenCalledWith("regime"));
    expect(await screen.findByText("TRENDING")).toBeInTheDocument();
  });

  it("tags a row as insufficient sample while still showing the raw count", async () => {
    strategyAnalyticsDimension.mockResolvedValue(breakdown("session", [
      { value: "Asian", sample_size: 2, wins: 1, losses: 1, breakeven: 0, win_rate: 50.0, avg_r: 0.0, total_r: 0.0, insufficient_sample: true },
    ]));
    render(<DimensionBreakdownPanel />);
    expect(await screen.findByText("Insufficient Sample")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("shows a no-trades state for an empty breakdown", async () => {
    strategyAnalyticsDimension.mockResolvedValue(breakdown("direction", []));
    render(<DimensionBreakdownPanel />);
    expect(await screen.findByText("No closed trades yet.")).toBeInTheDocument();
  });

  it("shows an error state when the request fails", async () => {
    strategyAnalyticsDimension.mockRejectedValue(new Error("network down"));
    render(<DimensionBreakdownPanel />);
    expect(await screen.findByText(/Unavailable/)).toBeInTheDocument();
  });

  it("never renders best/worst/winning-setup language", async () => {
    strategyAnalyticsDimension.mockResolvedValue(breakdown("direction", [
      { value: "BUY", sample_size: 8, wins: 5, losses: 3, breakeven: 0, win_rate: 62.5, avg_r: 0.5, total_r: 4.0, insufficient_sample: false },
    ]));
    render(<DimensionBreakdownPanel />);
    await screen.findByText("BUY");
    const bodyText = (document.body.textContent ?? "").toLowerCase();
    expect(bodyText).not.toContain("best");
    expect(bodyText).not.toContain("worst");
    expect(bodyText).not.toContain("winning");
  });
});
