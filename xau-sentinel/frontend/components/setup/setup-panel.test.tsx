import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
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
  it("collapses the checklist to a done/total count until expanded", () => {
    render(<SetupPanel setup={baseSetup} />);
    expect(screen.getByText("1/4")).toBeInTheDocument();
    expect(screen.queryByText("MSS")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Setup checklist/ }));
    expect(screen.getByText("Liquidity Sweep")).toBeInTheDocument();
    expect(screen.getByText("MSS")).toBeInTheDocument();
  });

  it('treats the NO-SETUP "WAITING" string as not done, without crashing', () => {
    const noSetup: Setup = {
      ...baseSetup,
      state: "NO SETUP",
      direction: null,
      checklist: { "Liquidity Sweep": "WAITING", MSS: "WAITING", Displacement: "WAITING", Retracement: "WAITING" },
    };
    render(<SetupPanel setup={noSetup} />);
    expect(screen.getByText("0/4")).toBeInTheDocument();
  });

  it("renders a placeholder when there is no setup data", () => {
    render(<SetupPanel setup={null} />);
    expect(screen.getByText("no data")).toBeInTheDocument();
  });
});
