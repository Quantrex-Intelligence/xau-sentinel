"use client";

import { Panel, PanelRow } from "@/components/layout/panel";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";
import { cn } from "@/lib/utils";
import type { StrategyAlignment } from "@/lib/types";

const ALIGNMENT_STYLE: Record<string, string> = {
  ALIGNED: "text-bullish bg-bullish/10",
  PARTIALLY_ALIGNED: "text-warning bg-warning/10",
  NOT_ALIGNED: "text-bearish bg-bearish/10",
  UNKNOWN: "text-muted-foreground bg-muted",
};

const ALIGNMENT_ORDER: StrategyAlignment[] = ["ALIGNED", "PARTIALLY_ALIGNED", "NOT_ALIGNED", "UNKNOWN"];

function AlignmentCounts({ title, counts }: { title: string; counts: Record<string, number> }) {
  return (
    <div className="mb-3">
      <p className="text-[11px] font-semibold text-muted-foreground uppercase mb-1">{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {ALIGNMENT_ORDER.map((a) => (
          <span
            key={a}
            className={cn("text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded", ALIGNMENT_STYLE[a])}
          >
            {a.replace(/_/g, " ")}: {counts[a] ?? 0}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Stage 17: descriptive-only rollup over completed trades, reusing
 * Stage 16's TradeReview alignment classification. No numeric confidence
 * score, no "best/worst" labeling — plain counts and rates only. */
export function StrategyAlignmentPanel() {
  const { data, error } = usePolling(() => api.strategyAnalytics(), 30000);

  return (
    <Panel title="Strategy Analytics">
      {error && <p className="text-xs text-bearish">Unavailable — {error.message}</p>}
      {!data && !error && <p className="text-xs text-muted-foreground">Loading…</p>}

      {data && (
        <>
          <PanelRow label="Median R">
            {data.overview.median_r !== null ? `${data.overview.median_r >= 0 ? "+" : ""}${data.overview.median_r}R` : "—"}
          </PanelRow>
          <PanelRow label="Avg Holding Duration">
            {data.overview.avg_holding_duration_minutes !== null
              ? `${Math.round(data.overview.avg_holding_duration_minutes)} min`
              : "—"}
          </PanelRow>

          <AlignmentCounts title="Strategy Alignment" counts={data.overview.strategy_alignment_counts} />
          <AlignmentCounts title="Risk Alignment" counts={data.overview.risk_alignment_counts} />

          <div className="mt-3">
            <p className="text-[11px] font-semibold text-muted-foreground uppercase mb-1">
              Adherence vs. Outcome
            </p>
            {data.adherence.length === 0 ? (
              <p className="text-xs text-muted-foreground">No closed trades yet.</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted-foreground text-left">
                    <th className="font-normal py-1">Alignment</th>
                    <th className="font-normal py-1 text-right">Trades</th>
                    <th className="font-normal py-1 text-right">Wins</th>
                    <th className="font-normal py-1 text-right">Losses</th>
                    <th className="font-normal py-1 text-right">BE</th>
                  </tr>
                </thead>
                <tbody>
                  {data.adherence.map((bucket) => (
                    <tr key={bucket.alignment} className="border-t border-border">
                      <td className="py-1">
                        <span className={cn("text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded", ALIGNMENT_STYLE[bucket.alignment])}>
                          {bucket.alignment.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="py-1 text-right font-mono">{bucket.trade_count}</td>
                      <td className="py-1 text-right font-mono text-bullish">{bucket.wins}</td>
                      <td className="py-1 text-right font-mono text-bearish">{bucket.losses}</td>
                      <td className="py-1 text-right font-mono text-warning">{bucket.breakeven}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </Panel>
  );
}
