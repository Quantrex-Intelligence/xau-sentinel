"use client";

import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/layout/panel";
import { formatPrice } from "@/lib/format";
import type { AnalysisV2KeyArea, AnalysisV2Lean, AnalysisV2Response } from "@/lib/types";
import { KindTag } from "@/components/analysis/shared";

const RELATION_TEXT: Record<string, string> = {
  INSIDE: "price inside",
  APPROACHING: "price approaching",
  ABOVE: "price above",
  BELOW: "price below",
  REJECTING: "recently rejected",
  BROKEN: "broken",
  UNKNOWN: "unknown",
};

const RELATION_VARIANT: Record<string, "bullish" | "bearish" | "warning" | "secondary" | "outline"> = {
  INSIDE: "warning",
  APPROACHING: "secondary",
  ABOVE: "outline",
  BELOW: "outline",
  REJECTING: "bearish",
  BROKEN: "bullish",
  UNKNOWN: "outline",
};

const LEAN_VARIANT: Record<AnalysisV2Lean["lean"], "bullish" | "bearish" | "secondary"> = {
  bullish: "bullish",
  bearish: "bearish",
  neutral: "secondary",
};

export function KeyAreasSection({ areas, price, distantCount = 0 }: { areas: AnalysisV2KeyArea[]; price: number | null; distantCount?: number }) {
  // Nearest first, by distance in ATR. Areas without a measurable distance go last.
  const sorted = [...areas].sort((a, b) => Math.abs(a.distance_atr ?? 1e9) - Math.abs(b.distance_atr ?? 1e9));
  return (
    <Panel title="Key areas" action={<KindTag kind="interpreted" />}>
      {sorted.length === 0 ? (
        <p className="text-sm text-muted-foreground">No key areas could be built from the current data.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {sorted.slice(0, 8).map((a) => (
            <li key={`${a.low}-${a.high}`} className="rounded-md border border-border px-3 py-2 flex flex-col gap-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono tabular-nums text-sm text-foreground">
                  {a.low === a.high ? formatPrice(a.low) : `${formatPrice(a.low)} – ${formatPrice(a.high)}`}
                </span>
                <Badge variant={RELATION_VARIANT[a.relation] ?? "outline"}>{RELATION_TEXT[a.relation] ?? a.relation.toLowerCase()}</Badge>
                {a.distance_atr !== null && a.distance_atr !== 0 && (
                  <span className="text-[11px] font-mono text-muted-foreground">{Math.abs(a.distance_atr).toFixed(2)} ATR</span>
                )}
                <Badge variant="outline" className="text-[10px]">strength: {a.strength_status.toLowerCase()}</Badge>
              </div>
              <p className="text-[11px] text-muted-foreground">
                {a.components.map((c) => `${c.label} (${c.timeframe})`).join(" · ")}
              </p>
              <ul className="text-[11px] text-muted-foreground list-disc pl-4">
                {a.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
      {distantCount > 0 && (
        <p className="mt-2 text-[11px] text-muted-foreground">{distantCount} more areas are further than the active distance from price and are not listed.</p>
      )}
      {price !== null && (
        <p className="mt-2 text-[11px] text-muted-foreground">Distances are measured from the last closed M5 price {formatPrice(price)}.</p>
      )}
    </Panel>
  );
}

export function ContextSection({ data }: { data: AnalysisV2Response }) {
  const ctx = data.interpretation.context;
  if (!ctx) {
    return (
      <Panel title="Market context" action={<KindTag kind="interpreted" />}>
        <p className="text-sm text-muted-foreground">Context needs closed H1, M15 and M5 history.</p>
      </Panel>
    );
  }
  const rows: Array<[string, { state: string; detail: string }]> = [
    ["Direction", ctx.direction],
    ["Regime", ctx.regime],
    ["Volatility", ctx.volatility],
    ["Volume", ctx.volume],
    ["Liquidity", ctx.liquidity],
    ["Momentum", ctx.momentum],
    ["Session", ctx.session],
    ["Price location", ctx.price_location],
    ["Trend strength", ctx.trend_strength],
  ];
  return (
    <Panel title="Market context" action={<KindTag kind="interpreted" />}>
      <p className="mb-2 text-[11px] text-muted-foreground">Each dimension is reported on its own and is never merged into a single summary.</p>
      <dl className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {rows.map(([label, dim]) => (
          <div key={label} className="rounded-md bg-muted/40 px-3 py-2">
            <dt className="flex items-center justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
              {label}
              <span className="font-mono normal-case text-foreground text-xs">{dim.state.replace(/_/g, " ").toLowerCase()}</span>
            </dt>
            <dd className="text-[11px] text-muted-foreground mt-0.5">{dim.detail}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

/** Plain count of observations. It is never a weight, a score, or a confidence value. */
function observationCount(n: number): string {
  return `${n} ${n === 1 ? "observation" : "observations"}`;
}

function LeanList({ title, items, tone }: { title: string; items: AnalysisV2Lean[]; tone: "bullish" | "bearish" | "neutral" }) {
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {title}
        <span className="ml-1.5 normal-case tracking-normal text-muted-foreground/80">· {observationCount(items.length)}</span>
      </p>
      {items.length === 0 ? (
        <p className="text-xs text-muted-foreground">None.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((l) => (
            <li key={`${l.source}-${l.detail}`} className="text-[11px] text-muted-foreground flex gap-2">
              <Badge variant={LEAN_VARIANT[tone]} className="shrink-0 text-[10px]">{l.timeframe || "—"}</Badge>
              <span><span className="text-foreground">{l.source}:</span> {l.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ConfluenceSection({ data }: { data: AnalysisV2Response }) {
  const c = data.interpretation.confluence;
  return (
    <Panel title="Confluence and contradictions" action={<KindTag kind="interpreted" />}>
      {!c ? (
        <p className="text-sm text-muted-foreground">No evidence to compare yet.</p>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-xs text-muted-foreground">{c.reference_reason}</p>
          <p className="text-[11px] text-muted-foreground">Each observation is listed with its source. Nothing is weighted, and the counts are not a rating.</p>
          {c.cross_timeframe_conflicts.length > 0 && (
            <div className="rounded-md border border-warning/40 bg-warning/5 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-warning mb-1">Timeframes disagree</p>
              <ul className="text-xs text-foreground list-disc pl-4">
                {c.cross_timeframe_conflicts.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <LeanList
              title={c.reference ? `Supporting the ${c.reference} reference` : "Supporting observations"}
              items={c.supporting}
              tone={c.reference ?? "neutral"}
            />
            <LeanList
              title={c.reference ? "Contradicting the reference" : "Opposing evidence"}
              items={c.contradicting}
              tone={c.reference === "bullish" ? "bearish" : c.reference === "bearish" ? "bullish" : "neutral"}
            />
          </div>
          <LeanList title="Neutral or non-directional" items={c.neutral} tone="neutral" />
        </div>
      )}
    </Panel>
  );
}

export function NarrativeSection({ lines }: { lines: string[] }) {
  return (
    <Panel title="Narrative" action={<KindTag kind="interpreted" />}>
      {lines.length === 0 ? (
        <p className="text-sm text-muted-foreground">No narrative is available for this data.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {lines.map((line, i) => (
            <li key={`${i}-${line.slice(0, 24)}`} className="text-sm text-foreground leading-relaxed">
              {line}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[11px] text-muted-foreground">Written from the structured results with fixed rules. No language model is involved.</p>
    </Panel>
  );
}
