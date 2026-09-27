import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { KnowledgeSources } from "./knowledge-sources";
import type { KnowledgeSource } from "@/lib/types";

const sample: KnowledgeSource = {
  source: "ai/strategy/rules.py", category: "strategy_rules", version: "1.0",
  title: "Locked A+ Strategy Rules", similarity: 0.42, excerpt: "Reward to risk ratio must be...",
};

describe("KnowledgeSources", () => {
  it("renders nothing when there are no sources", () => {
    const { container } = render(<KnowledgeSources sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the title and version for each retrieved source", () => {
    render(<KnowledgeSources sources={[sample]} />);
    expect(screen.getByText("Locked A+ Strategy Rules")).toBeInTheDocument();
    expect(screen.getByText("v1.0")).toBeInTheDocument();
  });

  it("renders multiple sources", () => {
    const second: KnowledgeSource = { ...sample, source: "risk/rules.py", title: "FundedNext Risk Rules" };
    render(<KnowledgeSources sources={[sample, second]} />);
    expect(screen.getByText("Locked A+ Strategy Rules")).toBeInTheDocument();
    expect(screen.getByText("FundedNext Risk Rules")).toBeInTheDocument();
  });
});
