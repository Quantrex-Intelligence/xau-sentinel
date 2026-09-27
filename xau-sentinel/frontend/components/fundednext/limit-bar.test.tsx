import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LimitBar } from "./limit-bar";

describe("LimitBar", () => {
  it("shows the floor and remaining amount", () => {
    render(<LimitBar title="Daily Loss Limit" floor={95000} remaining={2500} usedPct={50} />);
    expect(screen.getByText(/95,000/)).toBeInTheDocument();
    expect(screen.getByText(/2,500.*remaining/)).toBeInTheDocument();
    expect(screen.getByText("50% used")).toBeInTheDocument();
  });

  it("visually flags remaining <= 0 as breached (bold/red), not a normal remaining amount", () => {
    render(<LimitBar title="Daily Loss Limit" floor={95000} remaining={0} usedPct={100} />);
    const remainingText = screen.getByText(/remaining/);
    expect(remainingText.className).toContain("text-bearish");
  });

  it("clamps the visual bar width to 100% even when usedPct exceeds it", () => {
    const { container } = render(<LimitBar title="Maximum Loss Limit" floor={90000} remaining={-500} usedPct={110} />);
    const fill = container.querySelector(".bg-bearish");
    expect(fill).toHaveStyle({ width: "100%" });
  });
});
