"use client";

import { useState } from "react";
import { useMarket } from "@/lib/market-context";
import { CandlestickChart, type ChartOverlayToggles } from "@/components/charts/candlestick-chart";
import { ChartControls } from "@/components/charts/chart-controls";
import { StructurePanel } from "@/components/market/structure-panel";
import { RegimePanel } from "@/components/market/regime-panel";
import { LiquidityPanel } from "@/components/market/liquidity-panel";
import { SetupPanel } from "@/components/setup/setup-panel";
import type { Timeframe } from "@/lib/types";

export default function OverviewPage() {
  const { snapshot } = useMarket();
  const [timeframe, setTimeframe] = useState<Timeframe>("M5");
  const [overlays, setOverlays] = useState<ChartOverlayToggles>({ zones: true, liquidity: true, setup: true });

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
    <div className="p-4 flex flex-col gap-4">
      <div className="rounded-md border border-border bg-card">
        <ChartControls
          timeframe={timeframe}
          onTimeframeChange={setTimeframe}
          overlays={overlays}
          onOverlaysChange={setOverlays}
        />
        <div className="h-[440px] border-t border-border">
          <CandlestickChart
            timeframe={timeframe}
            zones={snapshot?.zones ?? {}}
            liquidity={snapshot?.liquidity ?? { sweeps: [], equal_levels: [] }}
            setup={snapshot?.setup ?? null}
            latestCandle={snapshot?.latest_m5_candle ?? null}
            overlays={overlays}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <StructurePanel structure={snapshot?.structure ?? {}} />
        <RegimePanel regime={snapshot?.regime ?? null} />
        <LiquidityPanel liquidity={snapshot?.liquidity ?? { sweeps: [], equal_levels: [] }} />
        <SetupPanel setup={snapshot?.setup ?? null} />
      </div>
    </div>
  );
}
