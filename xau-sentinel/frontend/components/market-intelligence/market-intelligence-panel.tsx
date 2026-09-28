"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { usePolling } from "@/lib/use-polling";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { EconomicEvent, NewsArticle } from "@/lib/types";

/** Stage 11: this panel displays external-source timestamps in
 * Asia/Phnom_Penh specifically (the spec-named display timezone) — scoped
 * to only this panel; internal storage and every other panel stay UTC. */
function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  try {
    return (
      new Date(iso).toLocaleString("en-US", {
        hour12: false,
        timeZone: "Asia/Phnom_Penh",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }) + " ICT"
    );
  } catch {
    return iso;
  }
}

function SourceBadge({ source }: { source: string }) {
  return (
    <span className="text-[9px] uppercase tracking-wide bg-muted text-muted-foreground px-1 py-0.5 rounded">
      {source}
    </span>
  );
}

/** LIVE/STALE/UNAVAILABLE/MOCK (ai/market_intelligence/models.py's
 * classify_freshness) — lets the user tell real-and-current data apart
 * from real-but-stale, missing, or synthetic mock data at a glance. */
const FRESHNESS_STYLES: Record<string, string> = {
  LIVE: "bg-bullish/10 text-bullish",
  STALE: "bg-warning/10 text-warning",
  UNAVAILABLE: "bg-bearish/10 text-bearish",
  MOCK: "bg-muted text-muted-foreground",
};

function FreshnessBadge({ freshness }: { freshness: string }) {
  return (
    <span
      className={cn(
        "text-[9px] uppercase tracking-wide px-1 py-0.5 rounded font-semibold",
        FRESHNESS_STYLES[freshness] ?? "bg-muted text-muted-foreground"
      )}
    >
      {freshness}
    </span>
  );
}

function Stat({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div>
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="text-xs font-mono text-foreground">{value ?? "—"}</p>
    </div>
  );
}

function EventRow({ event }: { event: EconomicEvent }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1 border-b border-border last:border-0 text-xs">
      <div className="min-w-0">
        <p className="text-foreground truncate">{event.name}</p>
        <p className="text-[10px] text-muted-foreground">{formatTimestamp(event.scheduled_at)}</p>
      </div>
      <div className="shrink-0 text-right text-[11px] text-muted-foreground">
        {event.actual && <span className="text-foreground">A: {event.actual} </span>}
        {event.forecast && <span>F: {event.forecast}</span>}
      </div>
    </div>
  );
}

function NewsRow({ article }: { article: NewsArticle }) {
  return (
    <div className="py-1.5 border-b border-border last:border-0">
      <p className="text-xs text-foreground">{article.headline}</p>
      <p className="text-[10px] text-muted-foreground">
        {article.source} · {formatTimestamp(article.published_at)}
      </p>
    </div>
  );
}

/** Stage 9: minimal, read-only exposure of the Market Intelligence layer —
 * macro/gold fundamentals/cross-asset/events/news, all external and
 * time-stamped, never authoritative over the deterministic engine. Mirrors
 * MemoryPanel's collapsible shape but has nothing to create or archive. */
export function MarketIntelligencePanel() {
  const [expanded, setExpanded] = useState(false);
  const { data: ctx, error } = usePolling(() => api.marketIntelligence(), 60000);

  return (
    <div className="rounded-md border border-border bg-card">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-1.5 px-4 py-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase"
      >
        {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        Market intelligence
      </button>

      {expanded && (
        <div className="px-4 pb-4 flex flex-col gap-3">
          <p className="text-xs text-muted-foreground -mt-1">
            External macro, gold-fundamentals, cross-asset, event, and news evidence — for context only,
            never authoritative over the deterministic setup engine.
          </p>

          {error && <p className="text-xs text-bearish">Unavailable — {error.message}</p>}
          {!ctx && !error && <p className="text-xs text-muted-foreground">Loading…</p>}

          {ctx && (
            <>
              {ctx.macro && (
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <p className="text-[11px] font-semibold text-muted-foreground uppercase">Macro</p>
                    <SourceBadge source={ctx.macro.source} />
                    <FreshnessBadge freshness={ctx.macro.freshness} />
                  </div>
                  {ctx.macro.data_available ? (
                    <div className="grid grid-cols-3 gap-2">
                      <Stat label="Fed Funds" value={ctx.macro.fed_funds_rate} />
                      <Stat label="CPI YoY" value={ctx.macro.cpi_yoy} />
                      <Stat label="Unemployment" value={ctx.macro.unemployment_rate} />
                      <Stat label="GDP YoY" value={ctx.macro.gdp_growth_yoy} />
                      <Stat label="US10Y" value={ctx.macro.us10y_yield} />
                      <Stat label="US2Y" value={ctx.macro.us2y_yield} />
                    </div>
                  ) : (
                    <p className="text-[11px] text-muted-foreground">{ctx.macro.reason ?? "No data available."}</p>
                  )}
                </div>
              )}

              {ctx.gold_fundamentals && (
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <p className="text-[11px] font-semibold text-muted-foreground uppercase">Gold Fundamentals</p>
                    <SourceBadge source={ctx.gold_fundamentals.source} />
                    <FreshnessBadge freshness={ctx.gold_fundamentals.freshness} />
                  </div>
                  {ctx.gold_fundamentals.data_available ? (
                    <div className="grid grid-cols-3 gap-2">
                      <Stat label="USD Bias" value={ctx.gold_fundamentals.usd_strength_bias} />
                      <Stat label="Real Yield 10Y" value={ctx.gold_fundamentals.real_yield_10y} />
                      <Stat label="CB Demand" value={ctx.gold_fundamentals.central_bank_demand_trend} />
                      <Stat label="ETF Flows" value={ctx.gold_fundamentals.etf_flows_trend} />
                    </div>
                  ) : (
                    <p className="text-[11px] text-muted-foreground">
                      {ctx.gold_fundamentals.reason ?? "No data available."}
                    </p>
                  )}
                </div>
              )}

              {ctx.cross_asset && (
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <p className="text-[11px] font-semibold text-muted-foreground uppercase">Cross-Asset</p>
                    <SourceBadge source={ctx.cross_asset.source} />
                    <FreshnessBadge freshness={ctx.cross_asset.freshness} />
                  </div>
                  {ctx.cross_asset.data_available ? (
                    <div className="grid grid-cols-3 gap-2">
                      <Stat label="DXY" value={ctx.cross_asset.dxy} />
                      <Stat label="VIX" value={ctx.cross_asset.vix} />
                      <Stat label="Silver" value={ctx.cross_asset.silver_price} />
                      <Stat label="US10Y" value={ctx.cross_asset.us10y_yield} />
                      <Stat label="US2Y" value={ctx.cross_asset.us2y_yield} />
                      <Stat label="Equity Idx" value={ctx.cross_asset.equity_index} />
                    </div>
                  ) : (
                    <p className="text-[11px] text-muted-foreground">
                      {ctx.cross_asset.reason ?? "No data available."}
                    </p>
                  )}
                </div>
              )}

              {ctx.events.length > 0 && (
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground uppercase mb-1">
                    Economic Events
                  </p>
                  {ctx.events.map((e, i) => <EventRow key={i} event={e} />)}
                </div>
              )}

              {ctx.news.length > 0 && (
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground uppercase mb-1">News</p>
                  {ctx.news.map((n) => <NewsRow key={n.id} article={n} />)}
                </div>
              )}

              <p className="text-[10px] text-muted-foreground">
                Generated {formatTimestamp(ctx.generated_at)}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
