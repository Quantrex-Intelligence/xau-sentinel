import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ContextIndicator } from "./context-indicator";
import type { ContextSource } from "@/lib/types";

describe("ContextIndicator", () => {
  it("renders each source label with a checkmark when available", () => {
    const sources: ContextSource[] = [
      { label: "Market Structure", category: "FACT", available: true, detail: "MOCK · price 3741.41" },
      { label: "Setup", category: "FACT", available: true, detail: "DEVELOPING (BUY)" },
    ];
    render(<ContextIndicator sources={sources} category="INTERPRETATION" />);

    expect(screen.getByText(/Market Structure/)).toBeInTheDocument();
    expect(screen.getByText(/Setup/)).toBeInTheDocument();
    expect(screen.getByText("Interpretation")).toBeInTheDocument();
  });

  it("visually distinguishes an unavailable source — never claims it was used", () => {
    const sources: ContextSource[] = [
      { label: "Journal", category: "UNKNOWN", available: false, detail: "0 trades" },
    ];
    render(<ContextIndicator sources={sources} category="UNKNOWN" />);

    const journalEntry = screen.getByText(/Journal/);
    expect(journalEntry.className).toContain("line-through");
    expect(screen.getByText("Unknown / insufficient data")).toBeInTheDocument();
  });

  it("renders a plain message when no sources were available at all", () => {
    render(<ContextIndicator sources={[]} category="UNKNOWN" />);
    expect(screen.getByText("No context was available for this answer.")).toBeInTheDocument();
  });
});
