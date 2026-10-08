import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnalysisScenarios } from "./analysis-scenarios";
import type { AnalysisV2Scenario } from "@/lib/types";

const DISCLAIMER = "Conditional scenarios describe what would need to happen. They are not predictions and not trade signals.";

function scenario(overrides: Partial<AnalysisV2Scenario> = {}): AnalysisV2Scenario {
  return {
    name: "REVERSAL",
    direction: "bearish",
    condition: "A reversal would start with a bearish structure shift on M5 against the bullish trend.",
    supporting_conditions: [],
    confirmation_requirements: ["M5 closes below 4341.78"],
    invalidation_conditions: ["M5 closes above 4356.72 (latest M5 swing high), which would undo the shift"],
    key_area_refs: [],
    event_refs: [],
    disclaimer: DISCLAIMER,
    state: "ACTIVE",
    invalidated_reason: "",
    ...overrides,
  };
}

describe("AnalysisScenarios invalidation state", () => {
  it("labels an invalidated scenario and shows the reason it is no longer live", () => {
    render(
      <AnalysisScenarios
        scenarios={[scenario({
          state: "INVALIDATED",
          invalidated_reason: "M5 closed above 4356.72 (last closed close 4370.26), so this scenario's invalidation has already occurred.",
        })]}
      />,
    );
    expect(screen.getByText("invalidated")).toBeTruthy();
    expect(screen.getByText(/last closed close 4370.26/)).toBeTruthy();
  });

  it("does not label an active scenario as invalidated", () => {
    render(<AnalysisScenarios scenarios={[scenario()]} />);
    expect(screen.queryByText("invalidated")).toBeNull();
  });
});
