// Labels for the Entry Model card (Top-Down Multi-Timeframe Entry Model). Presentation only: the
// states, checklist and confidence come from the API unchanged.

export const CHECK_MARK: Record<string, { glyph: string; cls: string; label: string }> = {
  PASS: { glyph: "✓", cls: "text-bullish", label: "pass" },
  FAIL: { glyph: "✕", cls: "text-bearish", label: "fail" },
  WAITING: { glyph: "○", cls: "text-muted-foreground", label: "waiting" },
  PARTIAL: { glyph: "◐", cls: "text-warning", label: "partial" },
  NOT_APPLICABLE: { glyph: "–", cls: "text-muted-foreground", label: "n/a" },
  INVALIDATED: { glyph: "✕", cls: "text-bearish", label: "invalidated" },
};

export function stateLabel(state: string): string {
  const words = state.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function headline(direction: string | null, symbol: string): string {
  if (direction === "LONG") return `${symbol} — LONG setup`;
  if (direction === "SHORT") return `${symbol} — SHORT setup`;
  if (direction === "CONFLICTED") return `${symbol} — conflicting evidence`;
  return `${symbol} — no setup`;
}

export function biasLabel(bias: unknown): string {
  if (bias === "bullish" || bias === "BULLISH") return "Bullish";
  if (bias === "bearish" || bias === "BEARISH") return "Bearish";
  if (bias === "TRANSITION") return "Transition";
  return "Neutral";
}

// The five rungs shown in the flow diagram, each mapped from the overall `state` to how far that
// rung's own evidence got -- "done" once the state has passed it, "active" while it is the current
// blocker, "pending" otherwise. Keeps the flow visual in sync with the single source of truth
// (`state`) rather than re-deriving it from the individual layers.
export const FLOW_STAGES = [
  { key: "htf", label: "1D / 4H", sub: "Location", reachedAt: "HTF_LOCATION_IDENTIFIED" },
  { key: "intraday", label: "1H", sub: "Intraday bias", reachedAt: "INTRADAY_BIAS_ESTABLISHED" },
  { key: "setup", label: "15M", sub: "Setup", reachedAt: "SETUP_DEVELOPING" },
  { key: "confirmation", label: "5M", sub: "Confirmation", reachedAt: "ENTRY_CONFIRMATION_DEVELOPING" },
  { key: "precision", label: "1M", sub: "Precision", reachedAt: "PRECISION_AVAILABLE" },
] as const;

const STATE_ORDER = [
  "NO_CONTEXT", "HTF_LOCATION_IDENTIFIED", "HTF_CONTEXT_ALIGNED", "INTRADAY_BIAS_ESTABLISHED",
  "SETUP_DEVELOPING", "SETUP_CONFIRMED", "ENTRY_CONFIRMATION_DEVELOPING", "ENTRY_CONFIRMED",
  "PRECISION_AVAILABLE", "ENTRY_READY",
];

export function flowStageStatus(state: string, reachedAt: string): "done" | "active" | "pending" {
  if (state === "INVALIDATED" || state === "EXPIRED" || state === "CONFLICTED") return "pending";
  const cur = STATE_ORDER.indexOf(state);
  const need = STATE_ORDER.indexOf(reachedAt);
  if (cur < 0 || need < 0) return "pending";
  if (cur > need) return "done";
  if (cur === need) return "active";
  return "pending";
}
