import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SuggestedQuestions } from "./suggested-questions";

describe("SuggestedQuestions", () => {
  it("calls onSelect with the question text and its scope when clicked", () => {
    const onSelect = vi.fn();
    render(<SuggestedQuestions onSelect={onSelect} />);

    fireEvent.click(screen.getByText("How much FundedNext daily loss do I have remaining?"));

    expect(onSelect).toHaveBeenCalledWith("How much FundedNext daily loss do I have remaining?", ["risk"]);
  });

  it("disables every button when disabled is true", () => {
    render(<SuggestedQuestions onSelect={vi.fn()} disabled />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) {
      expect(button).toBeDisabled();
    }
  });
});
