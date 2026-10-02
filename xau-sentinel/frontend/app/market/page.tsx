"use client";

import { useMarket } from "@/lib/market-context";
import { StructurePanel } from "@/components/market/structure-panel";
import { RegimePanel } from "@/components/market/regime-panel";
import { ZonesPanel } from "@/components/market/zones-panel";
import { LiquidityPanel } from "@/components/market/liquidity-panel";
import { EventsPanel } from "@/components/market/events-panel";

export default function MarketPage() {
  const { snapshot } = useMarket();

  return (
    <div className="p-4 flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-foreground tracking-tight">Market</h1>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <StructurePanel structure={snapshot?.structure ?? {}} />
        <RegimePanel regime={snapshot?.regime ?? null} />
        <ZonesPanel zones={snapshot?.zones ?? {}} />
        <LiquidityPanel liquidity={snapshot?.liquidity ?? { sweeps: [], equal_levels: [] }} />
        <div className="lg:col-span-2">
          <EventsPanel />
        </div>
      </div>
    </div>
  );
}
