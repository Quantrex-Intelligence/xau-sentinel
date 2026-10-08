import { describe, expect, it } from "vitest";
import {
  aplusLabel,
  biasFromStructure,
  checkState,
  marketStory,
  regimeLabel,
  riskLabel,
  scenarioViews,
  volatilityLabel,
} from "./market-view";
import type { AnalysisV2Response, AnalysisV2Scenario, StrategyCriterion } from "./types";

describe("Market labels", () => {
  it("maps structure states to a bias", () => {
    expect(biasFromStructure("BULLISH")).toBe("Bullish");
    expect(biasFromStructure("BEARISH")).toBe("Bearish");
    expect(biasFromStructure("RANGING")).toBe("Neutral");
    expect(biasFromStructure("PULLBACK")).toBe("Neutral");
    expect(biasFromStructure(undefined)).toBe("Neutral");
  });

  it("maps the existing regime names to the requested taxonomy", () => {
    expect(regimeLabel("TRENDING UP")).toBe("Trending");
    expect(regimeLabel("TRENDING DOWN")).toBe("Trending");
    expect(regimeLabel("RANGING")).toBe("Ranging");
    expect(regimeLabel("BREAKOUT")).toBe("Breakout");
    expect(regimeLabel("PULLBACK")).toBe("Transition");
    expect(regimeLabel("HIGH VOLATILITY")).toBe("Transition");
    expect(regimeLabel("UNKNOWN")).toBe("—");
    expect(regimeLabel(null)).toBe("—");
  });

  it("maps volatility states to low, normal or high", () => {
    expect(volatilityLabel("HIGH_EXPANDING")).toBe("High");
    expect(volatilityLabel("LOW")).toBe("Low");
    expect(volatilityLabel("NORMAL_CONTRACTING")).toBe("Normal");
    expect(volatilityLabel("UNKNOWN")).toBe("—");
  });

  it("maps the A+ rating to valid, developing or invalid", () => {
    expect(aplusLabel("A+")).toBe("Valid");
    expect(aplusLabel("DEVELOPING")).toBe("Developing");
    expect(aplusLabel("INVALID")).toBe("Invalid");
    expect(aplusLabel(undefined)).toBe("—");
  });

  it("maps the FundedNext safety level to SAFE, CAUTION or RESTRICTED", () => {
    expect(riskLabel("SAFE")).toBe("SAFE");
    expect(riskLabel("WARNING")).toBe("CAUTION");
    expect(riskLabel("CRITICAL")).toBe("RESTRICTED");
    expect(riskLabel("BREACHED")).toBe("RESTRICTED");
    expect(riskLabel("UNKNOWN")).toBe("UNKNOWN");
    expect(riskLabel(null)).toBe("UNKNOWN");
  });
});

describe("A+ checklist states", () => {
  const criterion = (status: StrategyCriterion["status"]): StrategyCriterion => ({
    name: "M5 MSS",
    status,
    evidence: "",
    required: true,
  });

  it("shows a passed condition as met", () => {
    expect(checkState(criterion("passed"), "DEVELOPING")).toBe("met");
  });

  it("shows a failed condition as waiting while the setup is still developing", () => {
    expect(checkState(criterion("failed"), "DEVELOPING")).toBe("waiting");
  });

  it("shows a failed condition as invalidated only when the evaluator rates the setup INVALID", () => {
    expect(checkState(criterion("failed"), "INVALID")).toBe("invalidated");
  });

  it("keeps an unknown condition unknown", () => {
    expect(checkState(criterion("unknown"), "DEVELOPING")).toBe("unknown");
  });
});

function v2(overrides: Partial<AnalysisV2Response["interpretation"]> & { scenarios?: AnalysisV2Scenario[] }): AnalysisV2Response {
  const { scenarios = [], ...interpretation } = overrides;
  return {
    interpretation: {
      context: null,
      key_areas: [],
      confluence: null,
      sequences: [],
      narrative: [],
      ...interpretation,
    },
    scenarios,
  } as unknown as AnalysisV2Response;
}

const SCENARIO = (overrides: Partial<AnalysisV2Scenario>): AnalysisV2Scenario => ({
  name: "CONTINUATION",
  direction: "bullish",
  condition: "Continuation needs M5 to close above the latest H1 swing high.",
  supporting_conditions: [],
  confirmation_requirements: ["M5 closes above 4383.45"],
  invalidation_conditions: ["M5 closes below 4342.63"],
  key_area_refs: [],
  event_refs: [],
  disclaimer: "",
  state: "ACTIVE",
  invalidated_reason: "",
  ...overrides,
});

describe("What matters now", () => {
  it("answers the five questions from the V2 narrative and scenario confirmations", () => {
    const story = marketStory(
      v2({
        narrative: [
          "Direction: H1 has no clear trend; H4 is up. Phase: trending.",
          "Price location: Price sits at 70% of the current day range 4339.94-4383.45.",
          "Nearby key areas: 4370.00-4371.16 (price is inside it); 4375.06 (price is approaching it, 0.96 ATR away).",
          "Recent events: 11:55 UTC M5: volatility expanded; 12:00 UTC M5: range expanded up.",
        ],
        scenarios: [SCENARIO({})],
      }),
    );
    expect(story.happening).toBe("H1 has no clear trend; H4 is up. Phase: trending.");
    expect(story.where).toBe("Price sits at 70% of the current day range 4339.94-4383.45.");
    expect(story.area).toBe("4370.00-4371.16 (price is inside it)");
    expect(story.justHappened).toBe("12:00 UTC M5: range expanded up");
    expect(story.waitingFor).toBe("M5 closes above 4383.45");
  });

  it("shows nothing for the recent event when the narrative reports none", () => {
    const story = marketStory(v2({ narrative: ["Recent events: none detected in the recent closed bars."] }));
    expect(story.justHappened).toBeNull();
  });

  it("returns empty answers when no analysis has loaded", () => {
    const story = marketStory(null);
    expect(story).toEqual({ happening: null, where: null, area: null, justHappened: null, waitingFor: null });
  });
});

describe("Scenarios", () => {
  it("takes the bullish and bearish cases from the scenario with that direction", () => {
    const views = scenarioViews(
      [SCENARIO({}), SCENARIO({ name: "REVERSAL", direction: "bearish", condition: "A reversal would start bearish." })],
      "M5 MSS",
    );
    expect(views.map((v) => v.key)).toEqual(["bullish", "bearish", "neutral"]);
    expect(views[0].meaning).toContain("Continuation");
    expect(views[1].meaning).toBe("A reversal would start bearish.");
  });

  it("marks an invalidated scenario and keeps its invalidation visible", () => {
    const [bullish] = scenarioViews(
      [SCENARIO({ state: "INVALIDATED", invalidated_reason: "M5 closed below 4342.63" })],
      null,
    );
    expect(bullish.invalidated).toBe(true);
    expect(bullish.invalidation).toBe("M5 closes below 4342.63");
  });

  it("falls back to the A+ wait condition for the neutral card when there is no range scenario", () => {
    const views = scenarioViews([SCENARIO({})], "Liquidity Sweep");
    expect(views[2].trigger).toBe("Liquidity Sweep");
    expect(views[2].meaning).toContain("wait");
  });

  it("leaves a side empty when no scenario exists for it", () => {
    const views = scenarioViews([], null);
    expect(views[0].meaning).toBeNull();
    expect(views[1].meaning).toBeNull();
  });
});
