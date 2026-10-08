// Cross-engine conflict detection for the unified Market page. Market Analysis V2 and Entry Model
// V2 remain two separate, unmerged engines (see docs/entry-model-v2-hierarchy.md and
// analysis/v2/context.py) -- this module only ever COMPARES two values each engine has already
// computed and formats a plain-language reason from fields both responses already expose. It
// never recomputes a market fact, a bias, or a setup state, and it never forces the two engines to
// agree: when they genuinely disagree, that disagreement is reported, not hidden or resolved.
import type { AnalysisV2Response, EntryModelResult } from "./types";

export type MarketBias = "Bullish" | "Bearish" | "Neutral";

export interface ConflictView {
  marketContext: MarketBias;
  entryModel: "CONFLICTED" | "LONG" | "SHORT";
  reason: string;
}

/** Analysis V2's own context.direction.state is "UP" | "DOWN" | "NONE" (a trend reading, see
 * analysis/v2/context.py::_trend_from_state). Mapped to the same Bullish/Bearish/Neutral words
 * used elsewhere on this page (e.g. SnapshotStrip's H1 bias tile) purely for display. */
function v2MarketBias(v2: AnalysisV2Response | null): MarketBias | null {
  const state = v2?.interpretation?.context?.direction?.state;
  if (state === "UP") return "Bullish";
  if (state === "DOWN") return "Bearish";
  if (state === "NONE") return "Neutral";
  return null;
}

function biasWord(b: "BULLISH" | "BEARISH" | string | null | undefined): "bullish" | "bearish" | null {
  if (b === "BULLISH") return "bullish";
  if (b === "BEARISH") return "bearish";
  return null;
}

function setupBiasWord(d: "LONG" | "SHORT" | "NEUTRAL" | "CONFLICTED" | null | undefined): "bullish" | "bearish" | null {
  if (d === "LONG") return "bullish";
  if (d === "SHORT") return "bearish";
  return null;
}

/** Names which rung's own evidence actually disagrees, using only fields Entry Model already
 * returns (higher_timeframe.htf_context, intraday.intraday_bias, setup_15m.setup_direction,
 * confirmation_5m.confirmation_status) -- the same rungs EntryModelCard already renders. Checked
 * top-down, so the highest-timeframe disagreement is named first, matching how the hierarchy
 * itself is read. */
function entryInternalConflictReason(entry: EntryModelResult): string {
  const htf = biasWord(entry.higher_timeframe?.htf_context);
  const intraday = biasWord(entry.intraday?.intraday_bias);
  const setup = setupBiasWord(entry.setup_15m?.setup_direction);

  if (htf && intraday && htf !== intraday) {
    return `1H bias (${intraday}) conflicts with the established 1D/4H context (${htf}).`;
  }
  if (intraday && setup && intraday !== setup) {
    return `15M ${setup} setup conflicts with the established 1H bias (${intraday}).`;
  }
  if (entry.confirmation_5m?.confirmation_status === "CONFLICTED") {
    return "5M confirmation evidence is split between both directions.";
  }
  return "Entry Model's own evidence is split between LONG and SHORT.";
}

/** Compares Market Analysis V2's context direction against Entry Model's exposed direction/state.
 * Returns null whenever there's nothing worth flagging: either side hasn't resolved to a direction
 * yet, or the two genuinely agree -- a missing/neutral reading on either side is NOT a conflict,
 * it's just not enough information yet. */
export function detectConflict(v2: AnalysisV2Response | null, entry: EntryModelResult | null): ConflictView | null {
  const market = v2MarketBias(v2);
  if (!market || market === "Neutral" || !entry) return null;

  if (entry.state === "CONFLICTED") {
    return { marketContext: market, entryModel: "CONFLICTED", reason: entryInternalConflictReason(entry) };
  }

  const entryBias = entry.direction === "LONG" ? "bullish" : entry.direction === "SHORT" ? "bearish" : null;
  if (entryBias && entryBias !== market.toLowerCase()) {
    return {
      marketContext: market,
      entryModel: entry.direction as "LONG" | "SHORT",
      reason: `Entry Model's confirmed ${entry.direction} direction is opposite the established market context (${market}).`,
    };
  }
  return null;
}
