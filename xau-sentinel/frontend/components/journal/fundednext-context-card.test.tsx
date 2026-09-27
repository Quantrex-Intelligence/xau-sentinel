import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { FundedNextContextCard } from "./fundednext-context-card";
import type { FundedNextTradeSnapshot } from "@/lib/types";

const available: FundedNextTradeSnapshot = {
  data_available: true,
  account_type: "stellar_2step",
  phase: "challenge",
  mode: "mock",
  balance: 50000,
  equity: 50100,
  today_pnl: 100,
  daily_loss_remaining: 2600,
  daily_loss_used_pct: 0,
  max_drawdown_remaining: 5100,
  max_drawdown_used_pct: 0,
  daily_loss_pct_rule: 0.05,
  max_loss_pct_rule: 0.1,
  safety_level: "SAFE",
  reason: "All FundedNext limits within safe range.",
  captured_at: "2026-01-05 10:00:00",
};

describe("FundedNextContextCard", () => {
  it("renders null (never captured) without crashing", () => {
    render(<FundedNextContextCard snapshot={null} />);
    expect(screen.getByText("Not captured for this trade.")).toBeInTheDocument();
  });

  it("renders an explicit UNKNOWN/UNAVAILABLE state, never fabricated numbers", () => {
    const unavailable: FundedNextTradeSnapshot = {
      ...available, data_available: false, balance: null, equity: null,
      safety_level: "UNKNOWN", reason: "MT5 not connected",
    };
    render(<FundedNextContextCard snapshot={unavailable} />);
    expect(screen.getByText(/UNKNOWN \/ DATA UNAVAILABLE/)).toBeInTheDocument();
    expect(screen.getByText(/MT5 not connected/)).toBeInTheDocument();
  });

  it("renders the captured figures and makes clear it's a frozen snapshot", () => {
    render(<FundedNextContextCard snapshot={available} />);
    expect(screen.getByText("Stellar 2-Step")).toBeInTheDocument();
    expect(screen.getByText("SAFE")).toBeInTheDocument();
    expect(screen.getByText(/frozen snapshot, not the account's current state/)).toBeInTheDocument();
  });
});
