"use client";

import { useMemo, useState } from "react";
import { useMarket } from "@/lib/market-context";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";
import { marketStory, scenarioViews } from "@/lib/market-view";
import { detectConflict } from "@/lib/market-conflict";
import type { Timeframe } from "@/lib/types";
import { CandlestickChart, type ChartOverlayToggles } from "@/components/charts/candlestick-chart";
import { ChartControls } from "@/components/charts/chart-controls";
import { Disclosure } from "@/components/layout/disclosure";
import { SnapshotStrip } from "@/components/market/snapshot-strip";
import { WhatMattersNow } from "@/components/market/what-matters-now";
import { AplusSetupCard } from "@/components/market/aplus-setup-card";
import { ScenariosCard } from "@/components/market/scenarios-card";
import { EntryModelCard } from "@/components/market/entry-model-card";
import { EntryJudgeCard } from "@/components/market/entry-judge-card";
import { ConflictBanner } from "@/components/market/conflict-banner";
import { StructurePanel } from "@/components/market/structure-panel";
import { ZonesPanel } from "@/components/market/zones-panel";
import { LiquidityPanel } from "@/components/market/liquidity-panel";
import { EventsPanel } from "@/components/market/events-panel";
import { AnalysisView } from "@/components/analysis/analysis-view";
import { AplusPanel } from "@/components/strategy/a-plus-panel";
import { SetupPanel } from "@/components/setup/setup-panel";
import { RiskPanel } from "@/components/risk/risk-panel";
import { AlertCenter } from "@/components/alerts/alert-center";
import { HistoricalSimilarityPanel } from "@/components/similarity/historical-similarity-panel";

// Minimal by default: the ICT overlay only. The other layers are one click away in the toggle row.
const DEFAULT_OVERLAYS: ChartOverlayToggles = {
  zones: false,
  liquidity: false,
  structure: false,
  areas: false,
  setup: false,
  ict: true,
};

export default function MarketPage() {
  const { snapshot } = useMarket();
  const [timeframe, setTimeframe] = useState<Timeframe>("M5");
  const [overlays, setOverlays] = useState<ChartOverlayToggles>(DEFAULT_OVERLAYS);

  // Read-only sources. Each one is the existing API; nothing here is recomputed.
  const v2 = usePolling(() => api.analysisV2(), 15000);
  const aplus = usePolling(() => api.strategyAPlus(), 15000);
  const risk = usePolling(() => api.fundedNextStatus(), 30000);
  const entry = usePolling(() => api.entryModel(), 30000);
  const entryJudge = usePolling(() => api.entryModelJudge(), 30000);

  const story = useMemo(() => marketStory(v2.data), [v2.data]);
  const nextCondition = aplus.data?.criteria.find((c) => c.status !== "passed")?.name ?? null;
  const scenarios = useMemo(
    () => scenarioViews(v2.data?.scenarios ?? [], nextCondition),
    [v2.data, nextCondition],
  );
  const conflict = useMemo(() => detectConflict(v2.data, entry.data), [v2.data, entry.data]);

  if (snapshot?.data_error) {
    return (
      <div className="p-6">
        <div className="rounded-md border border-bearish/30 bg-bearish/10 text-bearish p-4 text-sm">
          Market data unavailable: {snapshot.data_error}. Check your MT5 terminal/login, or switch MODE=mock.
        </div>
      </div>
    );
  }

  return (
    <div className="p-3 flex flex-col gap-3">
      <h1 className="sr-only">Market</h1>

      <SnapshotStrip snapshot={snapshot} v2={v2.data} entry={entry.data} risk={risk.data} />

      <div className="rounded-md border border-border bg-card">
        <ChartControls
          timeframe={timeframe}
          onTimeframeChange={setTimeframe}
          overlays={overlays}
          onOverlaysChange={setOverlays}
        />
        <div className="h-[400px] border-t border-border">
          <CandlestickChart
            timeframe={timeframe}
            zones={snapshot?.zones ?? {}}
            liquidity={snapshot?.liquidity ?? { sweeps: [], equal_levels: [] }}
            analysis={v2.data}
            aplus={aplus.data}
            latestCandle={snapshot?.latest_m5_candle ?? null}
            overlays={overlays}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <WhatMattersNow story={story} />
        <AplusSetupCard evaluation={aplus.data} />
      </div>

      <ConflictBanner conflict={conflict} />
      <div data-testid="entry-model-card">
        <EntryModelCard result={entry.data} />
      </div>
      <div data-testid="entry-judge-card">
        <EntryJudgeCard result={entryJudge.data} />
      </div>

      <ScenariosCard scenarios={scenarios} />

      <div className="flex flex-col gap-2">
        <Disclosure title="Full V2 analysis" summary="facts, events, key areas, confluence, scenarios">
          <div data-testid="full-v2-analysis">
            <AnalysisView data={v2.data} error={v2.error} loading={v2.loading} />
          </div>
        </Disclosure>
        <Disclosure title="Setup checklist, risk and alerts">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <div className="lg:col-span-2 flex flex-col gap-3">
              <SetupPanel setup={snapshot?.setup ?? null} />
            </div>
            <div className="flex flex-col gap-3">
              <RiskPanel risk={snapshot?.risk ?? null} />
              <AlertCenter />
            </div>
          </div>
        </Disclosure>
        <Disclosure title="A+ evidence and AI explanation">
          <AplusPanel />
        </Disclosure>
        <Disclosure title="Historical similarity">
          <HistoricalSimilarityPanel />
        </Disclosure>
        <Disclosure title="Structure, zones and liquidity">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <StructurePanel structure={snapshot?.structure ?? {}} />
            <ZonesPanel zones={snapshot?.zones ?? {}} />
            <LiquidityPanel liquidity={snapshot?.liquidity ?? { sweeps: [], equal_levels: [] }} />
            <EventsPanel />
          </div>
        </Disclosure>
      </div>
    </div>
  );
}
