import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryUsed } from "./memory-used";
import type { MemoryUsage } from "@/lib/types";

const sample: MemoryUsage = {
  id: 1, category: "TRADE_LESSON", excerpt: "Enters too early before the retracement.",
  similarity: 0.42, updated_at: "2026-01-01T00:00:00Z",
};

describe("MemoryUsed", () => {
  it("renders nothing when there are no memories", () => {
    const { container } = render(<MemoryUsed memories={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the category for each referenced memory", () => {
    render(<MemoryUsed memories={[sample]} />);
    expect(screen.getByText("TRADE_LESSON")).toBeInTheDocument();
  });

  it("renders multiple memories", () => {
    const second: MemoryUsage = { ...sample, id: 2, category: "USER_PREFERENCE" };
    render(<MemoryUsed memories={[sample, second]} />);
    expect(screen.getByText("TRADE_LESSON")).toBeInTheDocument();
    expect(screen.getByText("USER_PREFERENCE")).toBeInTheDocument();
  });
});
