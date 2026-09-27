import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TopBar } from "./top-bar";
import { MarketContext } from "@/lib/market-context";
import type { MarketSnapshot } from "@/lib/types";

function renderWithSnapshot(snapshot: MarketSnapshot | null, status: "connecting" | "open" | "closed" = "open") {
  return render(
    <MarketContext.Provider value={{ snapshot, status }}>
      <TopBar />
    </MarketContext.Provider>
  );
}

const baseSnapshot: MarketSnapshot = {
  connection: { label: "🟢 MT5 CONNECTED", connected: true, mode: "mock" },
  price: { price: 3741.5, bid: 3741.3, ask: 3741.7, spread: 0.4, time: Math.floor(Date.now() / 1000), source: "mock", stale: false },
  structure: {},
  regime: null,
  zones: {},
  liquidity: { sweeps: [], equal_levels: [] },
  displacement: null,
  setup: null,
  risk: { balance: 50000, risk_per_trade_pct: 0.3, today_r: 0 },
  session: null,
  latest_m5_candle: null,
  data_error: null,
};

describe("TopBar", () => {
  it('never claims LIVE before the first snapshot arrives (shows a neutral state instead)', () => {
    renderWithSnapshot(null, "connecting");
    expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
    // Both the price and the mode badge fall back to the same neutral dash.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText("CONNECTING…")).toBeInTheDocument();
  });

  it("shows MOCK when connection.mode is mock — never as LIVE", () => {
    renderWithSnapshot(baseSnapshot);
    expect(screen.getByText("MOCK")).toBeInTheDocument();
    expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
  });

  it("shows LIVE when connection.mode is live", () => {
    renderWithSnapshot({ ...baseSnapshot, connection: { ...baseSnapshot.connection, mode: "live" } });
    expect(screen.getByText("LIVE")).toBeInTheDocument();
  });

  it("shows a DATA STALE warning when price.stale is true", () => {
    renderWithSnapshot({ ...baseSnapshot, price: { ...baseSnapshot.price!, stale: true } });
    expect(screen.getByText(/DATA STALE/)).toBeInTheDocument();
  });

  it("does not show a stale warning for fresh data", () => {
    renderWithSnapshot(baseSnapshot);
    expect(screen.queryByText(/DATA STALE/)).not.toBeInTheDocument();
  });
});
