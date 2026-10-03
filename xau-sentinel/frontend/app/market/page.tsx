"use client";

import { useMarket } from "@/lib/market-context";
import { SummaryPanel } from "@/components/market/summary-strip";
import { StructurePanel } from "@/components/market/structure-panel";
import { ZonesPanel } from "@/components/market/zones-panel";
import { LiquidityPanel } from "@/components/market/liquidity-panel";
import { EventsPanel } from "@/components/market/events-panel";

export default function MarketPage() {
  const { snapshot } = useMarket();

  return (
    <div className="p-4 flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-foreground tracking-tight">Market</h1>
      <SummaryPanel
        structure={snapshot?.structure ?? {}}
        regime={snapshot?.regime ?? null}
        setup={snapshot?.setup ?? null}
      />
      <StructurePanel structure={snapshot?.structure ?? {}} />
      <div className="flex flex-col gap-3">
        <ZonesPanel zones={snapshot?.zones ?? {}} />
        <LiquidityPanel liquidity={snapshot?.liquidity ?? { sweeps: [], equal_levels: [] }} />
        <EventsPanel />
      </div>
    </div>
  );
}
