import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ToolsUsed } from "./tools-used";
import type { ToolUsage } from "@/lib/types";

const sample: ToolUsage = {
  name: "get_current_setup", label: "Current Setup", data_available: true,
  timestamp: "2026-01-01T00:00:00+00:00",
};

describe("ToolsUsed", () => {
  it("renders nothing when there are no tools", () => {
    const { container } = render(<ToolsUsed tools={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the label for each tool called", () => {
    render(<ToolsUsed tools={[sample]} />);
    expect(screen.getByText("Current Setup")).toBeInTheDocument();
  });

  it("renders multiple tools", () => {
    const second: ToolUsage = { ...sample, name: "get_risk_status", label: "FundedNext Risk Status" };
    render(<ToolsUsed tools={[sample, second]} />);
    expect(screen.getByText("Current Setup")).toBeInTheDocument();
    expect(screen.getByText("FundedNext Risk Status")).toBeInTheDocument();
  });

  it("distinguishes an unavailable tool result via its title attribute", () => {
    const unavailable: ToolUsage = { ...sample, data_available: false, timestamp: null };
    render(<ToolsUsed tools={[unavailable]} />);
    expect(screen.getByTitle("No data available")).toBeInTheDocument();
  });
});
