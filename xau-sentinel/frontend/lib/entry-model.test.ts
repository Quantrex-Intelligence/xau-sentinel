import { describe, expect, it } from "vitest";
import { biasLabel, CHECK_MARK, FLOW_STAGES, flowStageStatus, headline, stateLabel } from "./entry-model";

describe("Entry model labels", () => {
  it("renders every checklist status with a mark and a word, never colour alone", () => {
    for (const status of ["PASS", "FAIL", "WAITING", "PARTIAL", "NOT_APPLICABLE", "INVALIDATED"]) {
      expect(CHECK_MARK[status].glyph).toBeTruthy();
      expect(CHECK_MARK[status].label).toBeTruthy();
    }
  });

  it("names the state in plain words", () => {
    expect(stateLabel("RETRACEMENT_WAITING")).toBe("Retracement waiting");
    expect(stateLabel("ENTRY_READY")).toBe("Entry ready");
  });

  it("says no setup when there is no direction, and never says buy or sell", () => {
    expect(headline(null, "XAUUSD")).toBe("XAUUSD — no setup");
    expect(headline("LONG", "XAUUSD")).toBe("XAUUSD — LONG setup");
    expect(headline("SHORT", "XAUUSD")).toBe("XAUUSD — SHORT setup");
  });

  it("maps bias values to words", () => {
    expect(biasLabel("bullish")).toBe("Bullish");
    expect(biasLabel("bearish")).toBe("Bearish");
    expect(biasLabel("neutral")).toBe("Neutral");
    expect(biasLabel(undefined)).toBe("Neutral");
  });

  it("says conflicting evidence rather than forcing a direction", () => {
    expect(headline("CONFLICTED", "XAUUSD")).toBe("XAUUSD — conflicting evidence");
  });
});

describe("Entry model flow diagram", () => {
  it("marks every earlier stage done once a later state is reached", () => {
    expect(flowStageStatus("SETUP_DEVELOPING", "HTF_LOCATION_IDENTIFIED")).toBe("done");
    expect(flowStageStatus("SETUP_DEVELOPING", "INTRADAY_BIAS_ESTABLISHED")).toBe("done");
  });

  it("marks the current rung active and later rungs pending", () => {
    expect(flowStageStatus("SETUP_DEVELOPING", "SETUP_DEVELOPING")).toBe("active");
    expect(flowStageStatus("SETUP_DEVELOPING", "ENTRY_CONFIRMATION_DEVELOPING")).toBe("pending");
  });

  it("never marks a stage done or active when the setup is blocked", () => {
    for (const state of ["INVALIDATED", "EXPIRED", "CONFLICTED"]) {
      for (const stage of FLOW_STAGES) {
        expect(flowStageStatus(state, stage.reachedAt)).toBe("pending");
      }
    }
  });

  it("lists exactly the five hierarchy rungs, in order", () => {
    expect(FLOW_STAGES.map((s) => s.label)).toEqual(["1D / 4H", "1H", "15M", "5M", "1M"]);
  });
});
