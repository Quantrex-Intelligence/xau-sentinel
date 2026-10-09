import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EntryJudgeCard } from "./entry-judge-card";
import type { EntryModelJudgeResult } from "@/lib/types";

function result(overrides: Partial<EntryModelJudgeResult> = {}): EntryModelJudgeResult {
  return {
    enabled: true, eligible: true, status: "OK", error_category: null,
    candidate_key: "LONG:stop:4100.0", direction: "LONG", state: "ENTRY_READY", symbol: "XAUUSD",
    evaluated_at: "2026-10-08T12:00:00+00:00", candidate_created_at: "2026-10-08T11:45:00+00:00",
    is_reassessment: false, llm_provider: "anthropic", llm_model: "claude-haiku-4-5-20251001",
    prompt_version: "entry-judge-v1", verdict: "SUPPORTED", quality: "HIGH",
    supporting_evidence: ["M15 sweep + MSS confirmed"], contradictions: [], missing_confirmations: [],
    risk_flags: [], reasoning_summary: "Evidence is consistent across timeframes.",
    invalidation_conditions: ["Price closes back below the sweep low"], evidence_references: ["M15 SWEEP_LOW"],
    not_eligible_reason: null,
    disclaimer: "SHADOW MODE. This is an independent, experimental LLM review...",
    ...overrides,
  };
}

describe("EntryJudgeCard", () => {
  it("shows a waiting placeholder when nothing has loaded yet", () => {
    render(<EntryJudgeCard result={null} />);
    expect(screen.getByText(/waiting for the first evaluation/i)).toBeInTheDocument();
    expect(screen.getByText(/shadow mode/i)).toBeInTheDocument();
  });

  it("always shows the SHADOW MODE badge regardless of state", () => {
    for (const r of [
      result({ enabled: false }),
      result({ eligible: false, not_eligible_reason: "not yet" }),
      result({ status: "FAILED", error_category: "config", verdict: null, quality: null }),
      result(),
    ]) {
      const { unmount } = render(<EntryJudgeCard result={r} />);
      expect(screen.getAllByText(/shadow mode/i).length).toBeGreaterThan(0);
      unmount();
    }
  });

  it("shows a clear disabled message without a verdict", () => {
    render(<EntryJudgeCard result={result({ enabled: false, verdict: null })} />);
    expect(screen.getByText(/disabled/i)).toBeInTheDocument();
    expect(screen.queryByText("SUPPORTED")).not.toBeInTheDocument();
  });

  it("shows the not-eligible reason rather than a blank space", () => {
    render(<EntryJudgeCard result={result({ eligible: false, verdict: null, not_eligible_reason: "state is SETUP_DEVELOPING" })} />);
    expect(screen.getByText(/state is SETUP_DEVELOPING/i)).toBeInTheDocument();
  });

  it("shows a failure message, never a fabricated verdict", () => {
    render(<EntryJudgeCard result={result({ status: "FAILED", error_category: "malformed_response", verdict: null, quality: null })} />);
    expect(screen.getByText(/evaluation failed/i)).toBeInTheDocument();
    expect(screen.getByText(/malformed_response/i)).toBeInTheDocument();
    expect(screen.getByText(/unaffected/i)).toBeInTheDocument();
  });

  it("renders the verdict, quality, evidence, and never implies approval of a trade", () => {
    render(<EntryJudgeCard result={result()} />);
    expect(screen.getByText("SUPPORTED")).toBeInTheDocument();
    expect(screen.getByText(/evidence quality/i)).toBeInTheDocument();
    expect(screen.getByText(/consistent across timeframes/i)).toBeInTheDocument();
    expect(screen.getByText(/M15 sweep \+ MSS confirmed/)).toBeInTheDocument();
    expect(screen.getByText(/independent AI review/i)).toBeInTheDocument();
    expect(screen.queryByText(/approved|guaranteed|will win/i)).not.toBeInTheDocument();
  });

  it("omits empty evidence groups rather than showing empty headers", () => {
    render(<EntryJudgeCard result={result({ contradictions: [], risk_flags: [] })} />);
    expect(screen.queryByText(/^contradictions$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^risk flags$/i)).not.toBeInTheDocument();
  });
});
