"use client";

import { useMarket } from "@/lib/market-context";
import { formatAgo, formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Circle } from "lucide-react";

export function TopBar() {
  const { snapshot, status } = useMarket();
  const price = snapshot?.price;
  const conn = snapshot?.connection;
  // Before the first snapshot arrives, `conn` is undefined — must NOT default
  // to claiming LIVE (a false claim). Show a neutral "—" until the real mode
  // is known, per "never make mock data appear to be live" (and the inverse:
  // never imply live before we actually know).
  const modeLabel = conn ? (conn.mode === "mock" ? "MOCK" : "LIVE") : "—";

  return (
    <header className="h-14 shrink-0 border-b border-border bg-background flex items-center gap-6 px-4 text-sm">
      <span className="font-semibold text-foreground">XAUUSD</span>

      <span className="font-mono text-base text-foreground tabular-nums">
        {formatPrice(price?.price)}
      </span>

      {price && (
        <span className="hidden sm:flex items-center gap-3 text-xs text-muted-foreground font-mono tabular-nums">
          <span>Bid {formatPrice(price.bid)}</span>
          <span>Ask {formatPrice(price.ask)}</span>
          <span>Spread {formatPrice(price.spread)}</span>
        </span>
      )}

      <span
        className={cn(
          "flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded",
          !conn
            ? "text-muted-foreground bg-muted"
            : conn.mode === "mock"
              ? "text-warning bg-warning/10"
              : "text-bullish bg-bullish/10"
        )}
      >
        <Circle className="size-2 fill-current" />
        {modeLabel}
      </span>

      <span
        className={cn(
          "flex items-center gap-1.5 text-xs font-medium",
          !conn ? "text-muted-foreground" : conn.connected ? "text-bullish" : "text-bearish"
        )}
      >
        <Circle className="size-2 fill-current" />
        {conn ? (conn.connected ? "MT5 CONNECTED" : "MT5 DISCONNECTED") : "CONNECTING…"}
      </span>

      {price?.stale && (
        <span className="text-xs font-medium text-warning bg-warning/10 px-2 py-0.5 rounded">
          ⚠ DATA STALE
        </span>
      )}

      <span className="ml-auto flex items-center gap-4 text-xs text-muted-foreground">
        {price && <span>Updated {formatAgo(price.time)}</span>}
        <span
          className={cn(
            "flex items-center gap-1.5",
            status === "open" ? "text-bullish" : status === "connecting" ? "text-warning" : "text-bearish"
          )}
          title={status === "open" ? "Live stream connected" : status === "connecting" ? "Connecting…" : "Stream disconnected — retrying"}
        >
          <Circle className="size-2 fill-current" />
          {status === "open" ? "STREAM LIVE" : status === "connecting" ? "CONNECTING" : "RECONNECTING"}
        </span>
      </span>
    </header>
  );
}
