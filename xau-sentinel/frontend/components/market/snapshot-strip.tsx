"use client";

import type { AnalysisV2Response, EntryModelResult, FundedNextStatus, MarketSnapshot } from "@/lib/types";
import { formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";
import { stateLabel } from "@/lib/entry-model";
import {
  biasFromStructure,
  regimeLabel,
  riskLabel,
  volatilityLabel,
} from "@/lib/market-view";

type Tone = "bullish" | "bearish" | "warning" | "muted";

function feedStatus(snapshot: MarketSnapshot | null): { label: string; tone: Tone } {
  if (!snapshot) return { label: "Connecting", tone: "muted" };
  if (snapshot.data_error) return { label: "Data error", tone: "bearish" };
  if (!snapshot.connection.connected) return { label: "Disconnected", tone: "bearish" };
  if (snapshot.price?.stale) return { label: "Stale", tone: "warning" };
  return { label: `Live · ${snapshot.connection.mode}`, tone: "bullish" };
}

const TONE_TEXT: Record<Tone, string> = {
  bullish: "text-bullish",
  bearish: "text-bearish",
  warning: "text-warning",
  muted: "text-foreground",
};

function Tile({ label, value, tone = "muted" }: { label: string; value: string; tone?: Tone }) {
  return (
    <div className="rounded-md bg-muted/40 px-3 py-2 min-w-0">
      <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className={cn("text-sm font-semibold font-mono tabular-nums truncate", TONE_TEXT[tone])}>{value}</dd>
    </div>
  );
}

export function SnapshotStrip({
  snapshot,
  v2,
  entry,
  risk,
}: {
  snapshot: MarketSnapshot | null;
  v2: AnalysisV2Response | null;
  entry: EntryModelResult | null;
  risk: FundedNextStatus | null;
}) {
  const feed = feedStatus(snapshot);
  const bias = biasFromStructure(snapshot?.structure?.H1?.state);
  const biasTone: Tone = bias === "Bullish" ? "bullish" : bias === "Bearish" ? "bearish" : "muted";
  const regime = regimeLabel(snapshot?.regime?.regime ?? v2?.interpretation?.context?.regime.state);
  const vol = volatilityLabel(v2?.interpretation?.context?.volatility.state);
  const entryState = entry ? stateLabel(entry.state) : "—";
  const entryTone: Tone = entry?.direction === "LONG" ? "bullish" : entry?.direction === "SHORT" ? "bearish"
    : entry?.direction === "CONFLICTED" ? "warning" : "muted";
  const safety = riskLabel(risk?.safety_level ?? null);
  const safetyTone: Tone = safety === "SAFE" ? "bullish" : safety === "CAUTION" ? "warning" : safety === "RESTRICTED" ? "bearish" : "muted";
  const price = snapshot?.price?.price;

  return (
    <dl
      aria-label="Market snapshot"
      className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-2"
    >
      <Tile label="XAUUSD" value={price !== undefined ? formatPrice(price) : "—"} />
      <Tile label="Feed" value={feed.label} tone={feed.tone} />
      <Tile label="Session" value={snapshot?.session ?? "—"} />
      <Tile label="H1 bias" value={bias} tone={biasTone} />
      <Tile label="Regime" value={regime} />
      <Tile label="Volatility" value={vol} />
      <Tile label="Entry model" value={entryState} tone={entryTone} />
      <Tile label="Risk" value={safety} tone={safetyTone} />
    </dl>
  );
}
