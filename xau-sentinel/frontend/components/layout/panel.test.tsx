import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Panel } from "./panel";

describe("Panel", () => {
  it("exposes its title as a heading so headings and screen readers can find the section", () => {
    render(<Panel title="Historical Similarity">body</Panel>);
    expect(screen.getByRole("heading", { name: "Historical Similarity" })).toBeInTheDocument();
  });

  it("keeps the children rendered beneath the heading", () => {
    render(<Panel title="Risk">risk body</Panel>);
    expect(screen.getByRole("heading", { name: "Risk" })).toBeInTheDocument();
    expect(screen.getByText("risk body")).toBeInTheDocument();
  });
});
