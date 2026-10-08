import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EntryModelCard } from "./entry-model-card";
import type { EntryModelResult } from "@/lib/types";

function result(overrides: Partial<EntryModelResult> = {}): EntryModelResult {
  return {
    symbol: "XAUUSD", direction: null, state: "NO_CONTEXT", as_of: null,
    disclaimer: "Manual decision support only. No trade is placed automatically.",
    higher_timeframe: null, intraday: null, setup_15m: null, confirmation_5m: null,
    precision_1m: null, entry_candidate: null, confidence: null,
    supporting_evidence: [], contradicting_evidence: [], invalidation: null, next_condition: null,
    ...overrides,
  };
}

describe("EntryModelCard", () => {
  it("shows a waiting placeholder when no result has loaded yet", () => {
    render(<EntryModelCard result={null} />);
    expect(screen.getByText(/waiting for the first evaluation/i)).toBeInTheDocument();
  });

  it("says no setup without inventing a direction when nothing has resolved", () => {
    render(<EntryModelCard result={result()} />);
    expect(screen.getByText(/no setup/i)).toBeInTheDocument();
    expect(screen.queryByText(/LONG setup/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/SHORT setup/i)).not.toBeInTheDocument();
  });

  it("shows conflicting evidence rather than forcing a direction when the state is CONFLICTED", () => {
    render(<EntryModelCard result={result({ state: "CONFLICTED", direction: "CONFLICTED" })} />);
    expect(screen.getByText(/conflicting evidence/i)).toBeInTheDocument();
  });

  it("shows dashes for entry/stop/target when there is no candidate, never a fabricated setup", () => {
    render(<EntryModelCard result={result({ state: "SETUP_DEVELOPING" })} />);
    expect(screen.getByText("Waiting")).toBeInTheDocument(); // entry tile
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0); // stop/target tiles
  });

  it("renders entry, stop, target and R:R for a full candidate", () => {
    render(
      <EntryModelCard
        result={result({
          state: "ENTRY_READY", direction: "LONG",
          entry_candidate: {
            direction: "LONG", entry: 4100.5,
            stop: { price: 4095.0, basis: "beyond the sweep extreme" },
            target: { price: 4110.0, basis: "nearest opposing qualifying level" },
            rr: 0.67,
            invalidation: { price: 4095.0, basis: "beyond the sweep extreme" },
          },
        })}
      />,
    );
    expect(screen.getByText("4,100.50")).toBeInTheDocument();
    expect(screen.getByText("1:0.67")).toBeInTheDocument();
  });

  it("shows the strongest supporting evidence alongside any contradicting evidence", () => {
    const supporting = [
      { timeframe: "M15", timestamp: "2026-10-08T10:00:00+00:00", kind: "FVG", value: 4100, source: "setup_15m", note: "bullish FVG formed" },
    ];
    const contradicting = [
      { timeframe: "M15", timestamp: "2026-10-08T10:05:00+00:00", kind: "sweep", value: 4098, source: "setup_15m", note: "opposing sweep" },
    ];
    render(
      <EntryModelCard
        result={result({
          state: "SETUP_DEVELOPING",
          setup_15m: {
            setup_direction: "LONG", setup_status: "SETUP_DEVELOPING", evidence_categories: ["fvg"],
            supporting_evidence: supporting, contradicting_evidence: contradicting,
            fvg: null, ote: null, checklist: [],
          },
          // The merged, top-level lists EntryModelCard actually reads for the outside-disclosure
          // blocks (see analysis/entry_model/hierarchy.py's own supporting/contradicting merge).
          supporting_evidence: supporting, contradicting_evidence: contradicting,
        })}
      />,
    );
    expect(screen.getByTestId("strongest-evidence")).toHaveTextContent("bullish FVG formed");
    expect(screen.getByText(/opposing sweep/i)).toBeInTheDocument();
  });

  it("tags derived state and conditional information so they aren't mistaken for raw facts", () => {
    render(<EntryModelCard result={result({ state: "SETUP_DEVELOPING" })} />);
    expect(screen.getByText("Interpreted")).toBeInTheDocument();
    expect(screen.getByText("Conditional")).toBeInTheDocument();
  });
});
