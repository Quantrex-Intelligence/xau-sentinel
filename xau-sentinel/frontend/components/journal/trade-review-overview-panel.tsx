"use client";

import { Panel, PanelRow } from "@/components/layout/panel";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";
import type { BehavioralPattern } from "@/lib/types";

function PatternRow({ pattern }: { pattern: BehavioralPattern }) {
  const ratePct = pattern.occurrence_rate !== null ? `${(pattern.occurrence_rate * 100).toFixed(1)}%` : "—";
  return (
    <div className="py-1.5 border-b border-border last:border-0 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-foreground font-medium">{pattern.deviation_type.replace(/_/g, " ")}</span>
        <span className="text-muted-foreground">
          {pattern.sample_count} / {pattern.total_relevant_trades} ({ratePct})
        </span>
      </div>
      <p className="text-[10px] text-muted-foreground mt-0.5">{pattern.note}</p>
    </div>
  );
}

/** Stage 16: a journal-level behavioral summary — deterministic, no LLM,
 * safe to load automatically. Never shows a numeric confidence score;
 * patterns are gated server-side by TRADE_REVIEW_MIN_PATTERN_SAMPLE, so
 * whatever this renders already cleared that bar. */
export function TradeReviewOverviewPanel() {
  const { data: summary, error } = usePolling(() => api.tradeReviewSummary(), 30000);

  return (
    <Panel title="Trade Review Overview">
      {error && <p className="text-xs text-bearish">Unavailable — {error.message}</p>}
      {!summary && !error && <p className="text-xs text-muted-foreground">Loading…</p>}

      {summary && (
        <>
          <PanelRow label="Trades reviewed">{summary.trades_reviewed}</PanelRow>
          <PanelRow label="Strategy aligned">{summary.strategy_aligned}</PanelRow>
          <PanelRow label="Partially aligned">{summary.partially_aligned}</PanelRow>
          <PanelRow label="Not aligned">{summary.not_aligned}</PanelRow>
          <PanelRow label="Unknown">{summary.unknown}</PanelRow>

          <div className="mt-3">
            <p className="text-[11px] font-semibold text-muted-foreground uppercase mb-1">
              Recurring Observations
            </p>
            {summary.insufficient_sample_note ? (
              <p className="text-xs text-muted-foreground">{summary.insufficient_sample_note}</p>
            ) : summary.patterns.length === 0 ? (
              <p className="text-xs text-muted-foreground">No recurring patterns observed.</p>
            ) : (
              summary.patterns.map((p) => <PatternRow key={p.deviation_type} pattern={p} />)
            )}
          </div>
        </>
      )}
    </Panel>
  );
}
