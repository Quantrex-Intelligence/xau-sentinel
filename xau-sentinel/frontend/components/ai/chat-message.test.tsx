import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChatMessage, type ChatTurn } from "./chat-message";
import type { ChatResponse } from "@/lib/types";

const response: ChatResponse = {
  answer: "H1 structure is bullish.",
  conversation_id: "c1",
  context_used: ["Market Structure"],
  sources: [{ label: "Market Structure", category: "FACT", available: true, detail: null }],
  category: "INTERPRETATION",
  provider: "mock",
  model: "mock-deterministic-v1",
  created_at: "2026-01-01T00:00:00Z",
  knowledge_used: [],
};

describe("ChatMessage", () => {
  it("renders a user turn without a context indicator", () => {
    const turn: ChatTurn = { role: "user", content: "What is the current market structure?" };
    render(<ChatMessage turn={turn} />);
    expect(screen.getByText("What is the current market structure?")).toBeInTheDocument();
    expect(screen.queryByText(/Context used/)).not.toBeInTheDocument();
  });

  it("renders an assistant turn with its context indicator attached", () => {
    const turn: ChatTurn = { role: "assistant", content: response.answer, response };
    render(<ChatMessage turn={turn} />);
    expect(screen.getByText("H1 structure is bullish.")).toBeInTheDocument();
    expect(screen.getByText(/Context used/)).toBeInTheDocument();
  });

  it("renders knowledge sources alongside the context indicator when present", () => {
    const withKnowledge: ChatResponse = {
      ...response,
      knowledge_used: [{
        source: "ai/strategy/rules.py", category: "strategy_rules", version: "1.0",
        title: "Locked A+ Strategy Rules", similarity: 0.4, excerpt: "excerpt text",
      }],
    };
    const turn: ChatTurn = { role: "assistant", content: withKnowledge.answer, response: withKnowledge };
    render(<ChatMessage turn={turn} />);
    expect(screen.getByText("Locked A+ Strategy Rules")).toBeInTheDocument();
  });

  it("renders a client-side error turn distinctly, never as a normal answer", () => {
    const turn: ChatTurn = { role: "assistant", content: "AI assistant not configured: ...", isError: true };
    const { container } = render(<ChatMessage turn={turn} />);
    expect(screen.getByText(/not configured/)).toBeInTheDocument();
    expect(container.querySelector(".text-bearish")).not.toBeNull();
  });
});
