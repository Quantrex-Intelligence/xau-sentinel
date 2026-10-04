"use client";

import type { ReactNode } from "react";
import { Panel } from "@/components/layout/panel";
import { Badge } from "@/components/ui/badge";
import { formatPrice } from "@/lib/format";
import type { AnalysisV2Response, AnalysisV2Status, AnalysisV2TimeframeStructure } from "@/lib/types";
import {
  ConfluenceSection,
  ContextSection,
  KeyAreasSection,
  NarrativeSection,
} from "@/components/analysis/analysis-interpretation";
import { KindTag, utcClock } from "@/components/analysis/shared";
import { AnalysisScenarios } from "@/components/analysis/analysis-scenarios";

const STATUS_LABEL: Record<AnalysisV2Status, string> = {
  OK: "Live read",
  STALE: "Stale",
  INSUFFICIENT_DATA: "Insufficient data",
  UNAVAILABLE: "MT5 unavailable",
};

const STATUS_VARIANT: Record<AnalysisV2Status, "bullish" | "warning" | "bearish" | "secondary"> = {
  OK: "bullish",
  STALE: "warning",
  INSUFFICIENT_DATA: "warning",
  UNAVAILABLE: "bearish",
};

const STRUCTURE_VARIANT: Record<string, "bullish" | "bearish" | "warning" | "secondary" | "outline"> = {
  BULLISH: "bullish",
  BEARISH: "bearish",
  PULLBACK: "warning",
  RANGING: "secondary",
  INSUFFICIENT: "outline",
};

function Section({ title, kind, children }: { title: string; kind: "observed" | "interpreted" | "conditional"; children: ReactNode }) {
  return (
    <Panel title={title} action={<KindTag kind={kind} />}>
      {children}
    </Panel>
  );
}

function StatusBanner({ data }: { data: AnalysisV2Response }) {
  const { freshness, source } = data;
  const age = freshness.age_seconds;
  return (
    <div
      role="status"
      aria-label="Data freshness and source"
      className="rounded-lg border border-border bg-card px-4 py-3 flex flex-col gap-2 md:flex-row md:items-center md:justify-between"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={STATUS_VARIANT[data.status]}>{STATUS_LABEL[data.status]}</Badge>
        <span className="text-sm text-foreground">{data.status_reason}</span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground font-mono tabular-nums">
        <span>Source: {source.provider}</span>
        <span>Symbol: {source.symbol}</span>
        <span>Last closed M5: {utcClock(freshness.m5_bar_close_utc)}</span>
        <span>Age: {age === null ? "—" : `${Math.max(0, Math.round(age / 60))} min`}</span>
        <span>Server clock: {source.server_timezone}</span>
      </div>
      {data.notes.length > 0 && (
        <ul className="text-xs text-warning md:basis-full">
          {data.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Overview({ data }: { data: AnalysisV2Response }) {
  const obs = data.facts.observations;
  const ctx = data.interpretation.context;
  const confluence = data.interpretation.confluence;
  const items: Array<[string, string]> = [
    ["Price", obs ? formatPrice(obs.current_price) : "—"],
    ["Session", obs?.session ?? "—"],
    ["Direction", ctx ? ctx.direction.state : "—"],
    ["Regime", ctx ? ctx.regime.state : "—"],
    ["Reference", confluence?.reference ? `${confluence.reference} (H1/H4 trend)` : "none"],
    ["Volatility", ctx ? ctx.volatility.state.replace("_", " ").toLowerCase() : "—"],
    ["Volume", ctx ? ctx.volume.state.toLowerCase() : "—"],
    ["Liquidity", ctx ? ctx.liquidity.state.replace(/_/g, " ").toLowerCase() : "—"],
  ];
  return (
    <Section title="Market overview" kind="observed">
      <dl className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {items.map(([label, value]) => (
          <div key={label} className="rounded-md bg-muted/40 px-3 py-2">
            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</dt>
            <dd className="text-sm font-medium text-foreground font-mono tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}

function StructureGrid({ structure }: { structure: Record<string, AnalysisV2TimeframeStructure> }) {
  const order = ["H4", "H1", "M15", "M5"];
  return (
    <Section title="Multi-timeframe structure" kind="observed">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {order.map((tf) => {
          const s = structure[tf];
          if (!s) return null;
          return (
            <div key={tf} className="rounded-md border border-border px-3 py-2 flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-foreground">{tf}</span>
                <Badge variant={STRUCTURE_VARIANT[s.state] ?? "outline"}>{s.state.toLowerCase()}</Badge>
              </div>
              <p className="text-[11px] text-muted-foreground leading-snug">{s.reason}</p>
              <p className="text-[11px] font-mono tabular-nums text-foreground">
                High {s.last_high !== null ? formatPrice(s.last_high) : "—"} · Low {s.last_low !== null ? formatPrice(s.last_low) : "—"}
              </p>
              {(s.last_bos || s.last_mss) && (
                <p className="text-[11px] text-muted-foreground">
                  {s.last_bos ? `Last BOS ${s.last_bos}` : ""}
                  {s.last_bos && s.last_mss ? " · " : ""}
                  {s.last_mss ? `Last MSS ${s.last_mss}` : ""}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function EventsList({ data }: { data: AnalysisV2Response }) {
  const events = data.events.slice(-12).reverse();
  return (
    <Section title="Recent events" kind="observed">
      {events.length === 0 ? (
        <p className="text-sm text-muted-foreground">No events detected in the recent closed bars.</p>
      ) : (
        <ol className="flex flex-col divide-y divide-border">
          {events.map((e, i) => (
            <li key={`${e.time_utc}-${e.kind}-${i}`} className="py-2 flex flex-col gap-0.5">
              <div className="flex items-center gap-2 text-xs">
                <span className="font-mono tabular-nums text-muted-foreground">{utcClock(e.time_utc)}</span>
                <Badge variant="outline" className="text-[10px]">{e.timeframe}</Badge>
                <span className="font-medium text-foreground">{e.kind.replace(/_/g, " ").toLowerCase()}</span>
                {e.direction && <span className="text-muted-foreground">({e.direction})</span>}
              </div>
              <p className="text-xs text-muted-foreground">{e.detail}</p>
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

export function AnalysisView({ data, error, loading }: { data: AnalysisV2Response | null; error: Error | null; loading: boolean }) {
  if (error && !data) {
    return (
      <Panel title="Analysis unavailable">
        <p className="text-sm text-bearish">The analysis could not be loaded: {error.message}</p>
      </Panel>
    );
  }
  if (!data) {
    return (
      <Panel title="Loading analysis">
        <p className="text-sm text-muted-foreground">{loading ? "Reading closed candles from MT5…" : "No data yet."}</p>
      </Panel>
    );
  }
  const structure = data.facts.structure;
  return (
    <div className="flex flex-col gap-4">
      <StatusBanner data={data} />
      {data.status === "UNAVAILABLE" ? (
        <Panel title="No market data">
          <p className="text-sm text-muted-foreground">
            The analysis needs live candles from MT5. Nothing is shown rather than an estimate.
          </p>
        </Panel>
      ) : (
        <>
          {data.data_issues.length > 0 && (
            <Panel title="Data limits" density="compact">
              <ul className="text-xs text-warning list-disc pl-4">
                {data.data_issues.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            </Panel>
          )}
          <Overview data={data} />
          <StructureGrid structure={structure} />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <KeyAreasSection areas={data.interpretation.key_areas} price={data.facts.observations?.current_price ?? null} />
            <EventsList data={data} />
          </div>
          <ContextSection data={data} />
          <ConfluenceSection data={data} />
          <NarrativeSection lines={data.interpretation.narrative} />
          <AnalysisScenarios scenarios={data.scenarios} />
        </>
      )}
      <p className="text-[11px] text-muted-foreground px-1">
        {data.source.provider.startsWith("MOCK")
          ? "Synthetic test data is shown. It is not market data."
          : "Read-only. This view never places, closes, or modifies orders."}
      </p>
    </div>
  );
}
