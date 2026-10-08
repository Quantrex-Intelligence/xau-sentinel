// Presentation mapping for the unified Market page. Every function here only renames or
// selects values that the existing APIs already return. None of them recomputes a market
// fact, an A+ criterion or a risk rule.

import type {
  AnalysisV2Response,
  AnalysisV2Scenario,
  SafetyLevel,
  StrategyCriterion,
  StrategyRating,
  StructureState,
} from "./types";

export type Bias = "Bullish" | "Bearish" | "Neutral";

export function biasFromStructure(state: StructureState | null | undefined): Bias {
  if (state === "BULLISH") return "Bullish";
  if (state === "BEARISH") return "Bearish";
  return "Neutral";
}

export type RegimeLabel = "Trending" | "Ranging" | "Breakout" | "Transition" | "—";

/** Regime values come from the existing classify_regime(). Its volatility regimes have no
 * name in the requested taxonomy, so they read as Transition. */
export function regimeLabel(regime: string | null | undefined): RegimeLabel {
  const r = (regime ?? "").toUpperCase();
  if (!r || r === "UNKNOWN") return "—";
  if (r.startsWith("TRENDING")) return "Trending";
  if (r === "RANGING") return "Ranging";
  if (r === "BREAKOUT") return "Breakout";
  return "Transition";
}

export type VolatilityLabel = "Low" | "Normal" | "High" | "—";

export function volatilityLabel(state: string | null | undefined): VolatilityLabel {
  const v = (state ?? "").toUpperCase();
  if (!v || v === "UNKNOWN") return "—";
  if (v.startsWith("HIGH")) return "High";
  if (v.startsWith("LOW")) return "Low";
  if (v.startsWith("NORMAL")) return "Normal";
  return "—";
}

export type AplusLabel = "Valid" | "Developing" | "Invalid" | "—";

export function aplusLabel(rating: StrategyRating | null | undefined): AplusLabel {
  if (rating === "A+") return "Valid";
  if (rating === "DEVELOPING") return "Developing";
  if (rating === "INVALID") return "Invalid";
  return "—";
}

export type RiskLabel = "SAFE" | "CAUTION" | "RESTRICTED" | "UNKNOWN";

export function riskLabel(level: SafetyLevel | null | undefined): RiskLabel {
  if (level === "SAFE") return "SAFE";
  if (level === "WARNING") return "CAUTION";
  if (level === "CRITICAL" || level === "BREACHED") return "RESTRICTED";
  return "UNKNOWN";
}

export type CheckState = "met" | "waiting" | "invalidated" | "unknown";

/** One A+ condition as shown to the trader. A failed condition reads as "invalidated" only
 * when the evaluator itself reports the setup as INVALID. Otherwise it is still waiting. */
export function checkState(c: StrategyCriterion, rating: StrategyRating | null | undefined): CheckState {
  if (c.status === "passed") return "met";
  if (c.status === "failed") return rating === "INVALID" ? "invalidated" : "waiting";
  return "unknown";
}

function after(lines: string[], prefix: string): string | null {
  const line = lines.find((l) => l.startsWith(prefix));
  return line ? line.slice(prefix.length).trim() : null;
}

export interface MarketStory {
  happening: string | null;
  where: string | null;
  area: string | null;
  justHappened: string | null;
  waitingFor: string | null;
}

/** The five questions for "What Matters Now", taken from the V2 deterministic narrative and
 * the V2 scenario confirmations. One event at most is shown, so the raw stream stays out. */
export function marketStory(v2: AnalysisV2Response | null): MarketStory {
  const lines = v2?.interpretation?.narrative ?? [];
  const areas = after(lines, "Nearby key areas:");
  const recent = after(lines, "Recent events:");
  const lastEvent = recent && !recent.startsWith("none") ? recent.replace(/\.$/, "").split("; ").pop() ?? null : null;
  const firstScenario = v2?.scenarios?.[0];
  return {
    happening: after(lines, "Direction:"),
    where: after(lines, "Price location:"),
    area: areas && !areas.startsWith("none") ? areas.replace(/\.$/, "").split("; ")[0] : null,
    justHappened: lastEvent,
    waitingFor: firstScenario?.confirmation_requirements[0] ?? null,
  };
}

export type ScenarioStatus = "Active" | "Invalidated" | "—";

/** The scenario's own `state` field, in plain words. "—" only when no scenario exists at all for
 * this side (not the same as "Active" with nothing to show yet). */
function scenarioStatus(s: AnalysisV2Scenario | null): ScenarioStatus {
  if (!s) return "—";
  return s.state === "INVALIDATED" ? "Invalidated" : "Active";
}

export interface ScenarioView {
  key: "bullish" | "bearish" | "neutral";
  title: string;
  trigger: string | null;
  meaning: string | null;
  invalidation: string | null;
  invalidated: boolean;
  status: ScenarioStatus;
}

/** Bullish and bearish cases come from the scenario with that direction. Neutral is the RANGE
 * scenario when one exists, and otherwise the trader's wait condition from the A+ checklist. */
export function scenarioViews(
  scenarios: AnalysisV2Scenario[],
  nextCondition: string | null,
): ScenarioView[] {
  const pick = (direction: "bullish" | "bearish") => scenarios.find((s) => s.direction === direction) ?? null;
  const toView = (key: "bullish" | "bearish", title: string, s: AnalysisV2Scenario | null): ScenarioView => ({
    key,
    title,
    trigger: s?.confirmation_requirements[0] ?? null,
    meaning: s?.condition ?? null,
    invalidation: s ? (s.invalidation_conditions[0] ?? s.invalidated_reason ?? null) : null,
    invalidated: s?.state === "INVALIDATED",
    status: scenarioStatus(s),
  });
  const range = scenarios.find((s) => s.name === "RANGE") ?? null;
  return [
    toView("bullish", "Bullish", pick("bullish")),
    toView("bearish", "Bearish", pick("bearish")),
    {
      key: "neutral",
      title: "Neutral / wait",
      trigger: range?.confirmation_requirements[0] ?? nextCondition,
      meaning: range?.condition ?? "No range read. A directional reference is present, so wait for the next condition.",
      invalidation: range?.invalidation_conditions[0] ?? null,
      invalidated: range?.state === "INVALIDATED",
      status: range ? scenarioStatus(range) : (nextCondition ? "Active" : "—"),
    },
  ];
}
