"use client";

import { Panel, PanelRow } from "@/components/layout/panel";
import { Badge, type badgeVariants } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";
import type { StrategyAlignment } from "@/lib/types";
import type { VariantProps } from "class-variance-authority";

const ALIGNMENT_VARIANT: Record<string, VariantProps<typeof badgeVariants>["variant"]> = {
  ALIGNED: "bullish",
  PARTIALLY_ALIGNED: "warning",
  NOT_ALIGNED: "bearish",
  UNKNOWN: "secondary",
};

const ALIGNMENT_ORDER: StrategyAlignment[] = ["ALIGNED", "PARTIALLY_ALIGNED", "NOT_ALIGNED", "UNKNOWN"];
const SUB_LABEL = "text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-1";

function AlignmentCounts({ title, counts }: { title: string; counts: Record<string, number> }) {
  return (
    <div className="mb-3">
      <p className={SUB_LABEL}>{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {ALIGNMENT_ORDER.map((a) => (
          <Badge key={a} variant={ALIGNMENT_VARIANT[a]}>
            {a.replace(/_/g, " ")}: {counts[a] ?? 0}
          </Badge>
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
            <p className={SUB_LABEL}>Adherence vs. Outcome</p>
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
                        <Badge variant={ALIGNMENT_VARIANT[bucket.alignment]}>
                          {bucket.alignment.replace(/_/g, " ")}
                        </Badge>
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
