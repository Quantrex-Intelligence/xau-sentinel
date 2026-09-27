import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SafetyBanner } from "./safety-banner";

describe("SafetyBanner", () => {
  it.each([
    ["SAFE" as const, "SAFE"],
    ["WARNING" as const, "WARNING"],
    ["CRITICAL" as const, "CRITICAL"],
    ["BREACHED" as const, "BREACHED"],
  ])("renders the %s label for level %s", (level, expectedLabel) => {
    render(<SafetyBanner level={level} reason="test reason" />);
    expect(screen.getByText(expectedLabel)).toBeInTheDocument();
    expect(screen.getByText("test reason")).toBeInTheDocument();
  });

  it('renders "UNKNOWN / DATA UNAVAILABLE" for the UNKNOWN level, never a fabricated safe/unsafe claim', () => {
    render(<SafetyBanner level="UNKNOWN" reason="MT5 not connected" />);
    expect(screen.getByText("UNKNOWN / DATA UNAVAILABLE")).toBeInTheDocument();
  });
});
