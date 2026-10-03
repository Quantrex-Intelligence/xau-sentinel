import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SummaryPanel, deriveBias } from "./summary-strip";
import type { Setup, Structure, Timeframe } from "@/lib/types";

const structure = (state: Structure["state"]): Structure => ({
  state,
  last_bos: null,
  last_mss: null,
  reason: "",
  swings: [],
});

const setup = (over: Partial<Setup>): Setup => ({
  state: "DEVELOPING",
  direction: null,
  checklist: {},
  entry_zone: null,
  stop_loss: null,
  take_profit: null,
  rr: null,
  reason: "",
  ...over,
});

describe("deriveBias", () => {
  it("uses the setup direction when one is set", () => {
    const b = deriveBias(setup({ direction: "SELL" }), { H1: structure("BULLISH") });
    expect(b.label).toBe("Bearish");
    expect(b.basis).toContain("setup");
  });

  it("falls back to H1 structure when there is no setup direction", () => {
    const b = deriveBias(null, { H1: structure("BULLISH") as Structure, M5: structure("BEARISH") } as Partial<Record<Timeframe, Structure>>);
    expect(b.label).toBe("Bullish");
    expect(b.basis).toBe("H1 structure");
  });

  it("says no clear bias when H1 is ranging", () => {
    const b = deriveBias(null, { H1: structure("RANGING") });
    expect(b.label).toBe("No clear bias");
  });
});

describe("SummaryPanel", () => {
  it("shows the plan only when the setup is VALID", () => {
    const { rerender } = render(
      <SummaryPanel structure={{}} regime={null} setup={setup({ state: "DEVELOPING" })} />
    );
    expect(screen.queryByText("Stop")).not.toBeInTheDocument();

    rerender(
      <SummaryPanel
        structure={{}}
        regime={null}
        setup={setup({ state: "VALID", direction: "BUY", stop_loss: 3735, take_profit: 3750, rr: 2.4 })}
      />
    );
    expect(screen.getByText("Stop")).toBeInTheDocument();
    expect(screen.getByText("1:2.4")).toBeInTheDocument();
  });
});
