"use client";

import { useEffect, useState } from "react";
import { Panel } from "@/components/layout/panel";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { DimensionBreakdown } from "@/lib/types";

const DIMENSIONS: { value: string; label: string }[] = [
  { value: "direction", label: "Direction" },
  { value: "h1_bias", label: "H1 Bias" },
  { value: "session", label: "Session" },
  { value: "regime", label: "Regime" },
  { value: "liquidity", label: "Liquidity" },
  { value: "planned_rr", label: "R:R" },
];

/** Stage 17: a per-dimension breakdown table, purely descriptive — sample
 * size, win rate, and R by existing stored historical fields. Rows below
 * config.STRATEGY_ANALYTICS_MIN_SAMPLE carry an "Insufficient Sample" tag
 * but the raw count is always shown, never hidden. No "best/worst" or
 * "winning setup" labeling anywhere. */
export function DimensionBreakdownPanel() {
  const [dimension, setDimension] = useState("direction");
  // Same "fetch on prop/state change via useEffect + .then()" idiom already
  // established (and lint-passing) in trade-detail-sheet.tsx — both pieces
  // of state are only ever set from inside the async callback, never
  // synchronously in the effect body, and both are keyed by `dimension` so
  // a stale fetch can never overwrite the currently-selected one.
  const [fetched, setFetched] = useState<{ dimension: string; data: DimensionBreakdown } | null>(null);
  const [errored, setErrored] = useState<{ dimension: string; message: string } | null>(null);
  const breakdown = fetched?.dimension === dimension ? fetched.data : null;
  const error = errored?.dimension === dimension ? errored.message : null;

  useEffect(() => {
    let cancelled = false;
    api.strategyAnalyticsDimension(dimension).then(
      (data) => !cancelled && setFetched({ dimension, data }),
      (err) =>
        !cancelled &&
        setErrored({ dimension, message: err instanceof Error ? err.message : "Failed to load breakdown." })
    );
    return () => {
      cancelled = true;
    };
  }, [dimension]);

  return (
    <Panel title="Dimension Breakdown">
      <div className="flex flex-wrap gap-1.5 mb-3">
        {DIMENSIONS.map((d) => (
          <button
            key={d.value}
            onClick={() => setDimension(d.value)}
            className={cn(
              "text-[11px] px-2 py-1 rounded border",
              dimension === d.value
                ? "border-info bg-info/15 text-info"
                : "border-border text-muted-foreground hover:text-foreground"
            )}
          >
            {d.label}
          </button>
        ))}
      </div>

      {error && <p className="text-xs text-bearish">Unavailable — {error}</p>}
      {!breakdown && !error && <p className="text-xs text-muted-foreground">Loading…</p>}

      {breakdown && (
        breakdown.rows.length === 0 ? (
          <p className="text-xs text-muted-foreground">No closed trades yet.</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted-foreground text-left">
                <th className="font-normal py-1">Value</th>
                <th className="font-normal py-1 text-right">Sample</th>
                <th className="font-normal py-1 text-right">Wins</th>
                <th className="font-normal py-1 text-right">Losses</th>
                <th className="font-normal py-1 text-right">BE</th>
                <th className="font-normal py-1 text-right">Win Rate</th>
                <th className="font-normal py-1 text-right">Avg R</th>
                <th className="font-normal py-1 text-right">Total R</th>
              </tr>
            </thead>
            <tbody>
              {breakdown.rows.map((row) => (
                <tr key={row.value} className="border-t border-border">
                  <td className="py-1 text-foreground">
                    {row.value}
                    {row.insufficient_sample && (
                      <span className="ml-1.5 text-[9px] uppercase text-muted-foreground bg-muted px-1 py-0.5 rounded">
                        Insufficient Sample
                      </span>
                    )}
                  </td>
                  <td className="py-1 text-right font-mono">{row.sample_size}</td>
                  <td className="py-1 text-right font-mono text-bullish">{row.wins}</td>
                  <td className="py-1 text-right font-mono text-bearish">{row.losses}</td>
                  <td className="py-1 text-right font-mono text-warning">{row.breakeven}</td>
                  <td className="py-1 text-right font-mono">{row.win_rate !== null ? `${row.win_rate}%` : "—"}</td>
                  <td className="py-1 text-right font-mono">{row.avg_r !== null ? `${row.avg_r >= 0 ? "+" : ""}${row.avg_r}R` : "—"}</td>
                  <td className="py-1 text-right font-mono">{row.total_r >= 0 ? "+" : ""}{row.total_r}R</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      )}
    </Panel>
  );
}
