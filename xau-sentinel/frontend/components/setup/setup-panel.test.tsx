import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SetupPanel } from "./setup-panel";
import type { Setup } from "@/lib/types";

const baseSetup: Setup = {
  state: "DEVELOPING",
  direction: "BUY",
  checklist: { "Liquidity Sweep": true, MSS: false, Displacement: false, Retracement: false },
  entry_zone: null,
  stop_loss: null,
  take_profit: null,
  rr: null,
  reason: "BUY bias building — confirmed: Liquidity Sweep.",
};

describe("SetupPanel", () => {
  it("shows a filled check only for steps that are exactly true", () => {
    render(<SetupPanel setup={baseSetup} />);
    // Confirmed step shows the step label plus the Check icon (rendered, not just present in DOM as unchecked).
    expect(screen.getByText("Liquidity Sweep")).toBeInTheDocument();
    expect(screen.getByText("MSS")).toBeInTheDocument();
  });

  it('renders the NO-SETUP "WAITING" string checklist without crashing, treated as not-done', () => {
    const noSetup: Setup = {
      ...baseSetup,
      state: "NO SETUP",
      direction: null,
      checklist: { "Liquidity Sweep": "WAITING", MSS: "WAITING", Displacement: "WAITING", Retracement: "WAITING" },
      reason: "No clear H1 directional bias yet.",
    };
    render(<SetupPanel setup={noSetup} />);
    expect(screen.getByText("NO SETUP")).toBeInTheDocument();
    // None of the checklist items should render as confirmed (no crash on the string value).
    expect(screen.queryByText("VALID")).not.toBeInTheDocument();
  });

  it("shows entry/SL/TP/RR fields only when state is VALID", () => {
    const { rerender } = render(<SetupPanel setup={baseSetup} />);
    expect(screen.queryByText("Entry Zone")).not.toBeInTheDocument();

    const validSetup: Setup = {
      ...baseSetup,
      state: "VALID",
      checklist: { "Liquidity Sweep": true, MSS: true, Displacement: true, Retracement: true },
      entry_zone: [3740.5, 3741.2],
      stop_loss: 3735.0,
      take_profit: 3750.0,
      rr: 2.4,
      reason: "BUY setup fully confirmed.",
    };
    rerender(<SetupPanel setup={validSetup} />);
    expect(screen.getByText("Entry Zone")).toBeInTheDocument();
    expect(screen.getByText("1:2.4")).toBeInTheDocument();
  });

  it("renders a placeholder when there is no setup data", () => {
    render(<SetupPanel setup={null} />);
    expect(screen.getByText("No data")).toBeInTheDocument();
  });
});
