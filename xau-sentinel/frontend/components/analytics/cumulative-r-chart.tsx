"use client";

import type { Trade } from "@/lib/types";

/** Plots the running sum of already-known per-trade r_multiple values — a
 * plotting transform of raw data, not a re-derivation of compute_analytics'
 * aggregate math (win rate / profit factor / etc. still come straight from
 * the API). */
export function CumulativeRChart({ trades }: { trades: Trade[] }) {
  const closed = trades
    .filter((t) => t.status === "CLOSED" && t.r_multiple !== null)
    .sort((a, b) => `${a.trade_date}${a.trade_time}`.localeCompare(`${b.trade_date}${b.trade_time}`));

  if (closed.length === 0) {
    return <p className="text-xs text-muted-foreground">No closed trades yet.</p>;
  }

  const points = closed.reduce<number[]>((acc, t) => {
    const previous = acc.length > 0 ? acc[acc.length - 1] : 0;
    return [...acc, previous + t.r_multiple!];
  }, []);
  const min = Math.min(0, ...points);
  const max = Math.max(0, ...points);
  const range = max - min || 1;

  const width = 600;
  const height = 140;
  const pad = 8;
  const step = points.length > 1 ? (width - pad * 2) / (points.length - 1) : 0;

  const toXY = (i: number, v: number) => {
    const x = pad + i * step;
    const y = height - pad - ((v - min) / range) * (height - pad * 2);
    return [x, y];
  };

  const path = points.map((v, i) => toXY(i, v).join(",")).join(" ");
  const zeroY = toXY(0, 0)[1];
  const lastValue = points[points.length - 1];

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-[140px]" preserveAspectRatio="none">
        <line x1={pad} y1={zeroY} x2={width - pad} y2={zeroY} stroke="#242832" strokeWidth={1} />
        <polyline
          points={path}
          fill="none"
          stroke={lastValue >= 0 ? "#26a69a" : "#ef5350"}
          strokeWidth={2}
        />
      </svg>
      <p className="text-xs text-muted-foreground mt-1">
        {closed.length} closed trade{closed.length === 1 ? "" : "s"} · running total{" "}
        <span className={lastValue >= 0 ? "text-bullish" : "text-bearish"}>
          {lastValue >= 0 ? "+" : ""}
          {lastValue.toFixed(2)}R
        </span>
      </p>
    </div>
  );
}
