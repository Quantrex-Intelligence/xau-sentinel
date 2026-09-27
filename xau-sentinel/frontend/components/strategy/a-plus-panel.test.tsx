import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { AplusPanel } from "./a-plus-panel";
import type { StrategyEvaluation } from "@/lib/types";

const { strategyAPlus } = vi.hoisted(() => ({ strategyAPlus: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { strategyAPlus } }));

const developing: StrategyEvaluation = {
  rating: "DEVELOPING",
  direction: "BUY",
  criteria: [
    { name: "H1 Bias", status: "passed", evidence: "H1 structure: BULLISH", required: true },
    { name: "Liquidity Sweep", status: "passed", evidence: "Previous Day Low swept at 3699.9", required: true },
    { name: "M5 MSS", status: "failed", evidence: "M5 structure: BULLISH", required: true },
  ],
  context_evidence: ["H4 bias: BULLISH — uptrend intact."],
  missing_conditions: ["M5 MSS"],
  invalidation: null,
  entry: 3705.0,
  stop_loss: 3699.6,
  target: 3720.0,
  rr: 3.9,
  fundednext: {
    data_available: true, safety_level: "SAFE", daily_loss_used_pct: 10.0,
    max_daily_loss_used_pct_allowed: 50.0, reason: "SAFE and daily loss used is below the A+ limit.",
  },
  evaluated_at: "2026-01-05T12:00:00Z",
  candidate_sweep_time: "2026-01-05T11:50:00Z",
  llm_explanation: null,
  llm_provider: null,
  llm_model: null,
  llm_error: null,
};

describe("AplusPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the rating, direction, and criteria checklist", async () => {
    strategyAPlus.mockResolvedValue(developing);
    render(<AplusPanel />);

    await waitFor(() => expect(screen.getByText(/DEVELOPING/)).toBeInTheDocument());
    expect(screen.getByText(/BUY/)).toBeInTheDocument();
    expect(screen.getByText("H1 Bias")).toBeInTheDocument();
    expect(screen.getByText("M5 MSS")).toBeInTheDocument();
    expect(screen.getByText(/Missing: M5 MSS/)).toBeInTheDocument();
  });

  it("shows the FundedNext safety level and daily-loss figure", async () => {
    strategyAPlus.mockResolvedValue(developing);
    render(<AplusPanel />);
    await waitFor(() => expect(screen.getByText(/SAFE/)).toBeInTheDocument());
    expect(screen.getByText(/daily loss used 10/)).toBeInTheDocument();
  });

  it("shows entry/SL/target/RR once an entry has been planned", async () => {
    strategyAPlus.mockResolvedValue(developing);
    render(<AplusPanel />);
    await waitFor(() => expect(screen.getByText("Entry")).toBeInTheDocument());
    expect(screen.getByText("Target")).toBeInTheDocument();
    expect(screen.getByText("1:3.9")).toBeInTheDocument();
  });

  it("renders the invalidation reason distinctly when the rating is INVALID", async () => {
    strategyAPlus.mockResolvedValue({
      ...developing, rating: "INVALID", missing_conditions: [], criteria: [],
      invalidation: "Setup expired — no entry within 60 minutes of the Previous Day Low sweep.",
    });
    render(<AplusPanel />);
    await waitFor(() => expect(screen.getByText(/Setup expired/)).toBeInTheDocument());
  });

  it("shows an AI explanation when the provider returned one", async () => {
    strategyAPlus.mockResolvedValue({ ...developing, llm_explanation: "H1 is bullish but M5 has not shifted yet." });
    render(<AplusPanel />);
    await waitFor(() => expect(screen.getByText(/H1 is bullish but M5/)).toBeInTheDocument());
  });

  it("shows the llm_error instead of a fabricated explanation when the provider failed", async () => {
    strategyAPlus.mockResolvedValue({
      ...developing, llm_explanation: null, llm_error: "AI assistant not configured: AI_API_KEY is not set.",
    });
    render(<AplusPanel />);
    await waitFor(() => expect(screen.getByText(/AI assistant not configured/)).toBeInTheDocument());
  });

  it("shows a loading state before the first response arrives", () => {
    strategyAPlus.mockReturnValue(new Promise(() => {})); // never resolves
    render(<AplusPanel />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("shows an error state when the request fails, never a stale/fabricated result", async () => {
    strategyAPlus.mockRejectedValue(new Error("Network error"));
    render(<AplusPanel />);
    await waitFor(() => expect(screen.getByText(/Evaluation unavailable/)).toBeInTheDocument());
  });
});
