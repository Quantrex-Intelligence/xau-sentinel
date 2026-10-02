"use client";

import { Panel } from "@/components/layout/panel";
import { Card, CardContent } from "@/components/ui/card";
import { CumulativeRChart } from "@/components/analytics/cumulative-r-chart";
import { WinLossBar } from "@/components/analytics/win-loss-bar";
import { StrategyAlignmentPanel } from "@/components/analytics/strategy-alignment-panel";
import { DimensionBreakdownPanel } from "@/components/analytics/dimension-breakdown-panel";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";
import { cn } from "@/lib/utils";

export default function AnalyticsPage() {
  const { data: stats } = usePolling(() => api.analytics(), 5000);
  const { data: trades } = usePolling(() => api.trades(), 5000);

  if (!stats) return null;

  return (
    <div className="p-4 flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-foreground tracking-tight">Analytics</h1>

      {stats.total_trades < 10 && stats.total_trades > 0 && (
        <div className="rounded-md border border-warning/30 bg-warning/10 text-warning text-sm px-3 py-2">
          Sample size: {stats.total_trades} closed trades — too small to draw firm conclusions.
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <Stat label="Total Trades" value={String(stats.total_trades)} />
        <Stat label="Win Rate" value={`${stats.win_rate}%`} />
        <Stat label="Total R" value={`${stats.total_r >= 0 ? "+" : ""}${stats.total_r}R`} tone={stats.total_r >= 0 ? "bullish" : "bearish"} />
        <Stat label="Avg R" value={`${stats.avg_r >= 0 ? "+" : ""}${stats.avg_r}R`} tone={stats.avg_r >= 0 ? "bullish" : "bearish"} />
        <Stat label="Profit Factor" value={stats.profit_factor !== null ? String(stats.profit_factor) : "—"} />
        <Stat label="Wins / Losses" value={`${stats.wins} / ${stats.losses}`} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Panel title="Cumulative R">
          <CumulativeRChart trades={trades ?? []} />
        </Panel>

        <Panel title="Win / Loss Distribution">
          <WinLossBar stats={stats} />
        </Panel>

        <StrategyAlignmentPanel />
        <div className="xl:col-span-2">
          <DimensionBreakdownPanel />
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "bullish" | "bearish" }) {
  return (
    <Card size="sm">
      <CardContent>
        <p className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1">{label}</p>
        <p className={cn("text-xl font-semibold font-mono", tone === "bullish" ? "text-bullish" : tone === "bearish" ? "text-bearish" : "text-foreground")}>
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
