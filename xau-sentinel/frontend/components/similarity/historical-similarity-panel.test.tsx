import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { HistoricalSimilarityPanel } from "./historical-similarity-panel";
import type { SimilarityResult } from "@/lib/types";

const { similarityCurrent } = vi.hoisted(() => ({ similarityCurrent: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { similarityCurrent } }));

const emptyFeatures = {
  direction: "BUY", h4_structure: "BULLISH", h1_structure: "BULLISH", m15_structure: "PULLBACK",
  m5_structure: "BULLISH", regime: "TRENDING UP", liquidity_kind: "sweep_low",
  mss_direction: "bullish", displacement: "bullish", session: "London", planned_rr: 2.5,
};

const withMatches: SimilarityResult = {
  query_features: emptyFeatures,
  matches: [
    {
      trade_id: 183, similarity: 0.87,
      entry_snapshot: emptyFeatures,
      outcome: { status: "CLOSED", result: "WIN", r_multiple: 2.0, pnl: 500, duration_minutes: 45,
                 entry_date: "2026-01-01", entry_time: "09:00:00" },
      matched_features: ["h1_structure", "liquidity_kind"],
      different_features: ["session"],
    },
  ],
  considered_count: 3,
  excluded_count: 1,
};

const noMatches: SimilarityResult = {
  query_features: emptyFeatures, matches: [], considered_count: 0, excluded_count: 0,
};

describe("HistoricalSimilarityPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a loading state before data arrives", () => {
    similarityCurrent.mockReturnValue(new Promise(() => {}));
    render(<HistoricalSimilarityPanel />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders match count, similarity, outcome, and feature chips", async () => {
    similarityCurrent.mockResolvedValue(withMatches);
    render(<HistoricalSimilarityPanel />);

    await waitFor(() => expect(screen.getByText(/Trade #183/)).toBeInTheDocument());
    expect(screen.getByText("87%")).toBeInTheDocument();
    expect(screen.getByText("WIN")).toBeInTheDocument();
    expect(screen.getByText("+2.00R")).toBeInTheDocument();
    expect(screen.getByText("h1 structure")).toBeInTheDocument();
    expect(screen.getByText("session")).toBeInTheDocument();
  });

  it("renders a no-matches message when nothing similar is found", async () => {
    similarityCurrent.mockResolvedValue(noMatches);
    render(<HistoricalSimilarityPanel />);
    await waitFor(() =>
      expect(screen.getByText("No sufficiently similar historical setups found.")).toBeInTheDocument()
    );
  });

  it("never renders probability or confidence language", async () => {
    similarityCurrent.mockResolvedValue(withMatches);
    render(<HistoricalSimilarityPanel />);
    await waitFor(() => expect(screen.getByText(/Trade #183/)).toBeInTheDocument());
    const bodyText = document.body.textContent ?? "";
    expect(bodyText.toLowerCase()).not.toContain("probability");
    expect(bodyText.toLowerCase()).not.toContain("confidence");
    expect(bodyText.toLowerCase()).not.toContain("chance of winning");
  });

  it("shows the excluded-count note when some trades lacked entry data", async () => {
    similarityCurrent.mockResolvedValue(withMatches);
    render(<HistoricalSimilarityPanel />);
    await waitFor(() => expect(screen.getByText(/excluded/)).toBeInTheDocument());
  });
});
