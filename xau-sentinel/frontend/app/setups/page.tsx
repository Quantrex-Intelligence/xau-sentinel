"use client";

import { useMarket } from "@/lib/market-context";
import { SetupPanel } from "@/components/setup/setup-panel";
import { AplusPanel } from "@/components/strategy/a-plus-panel";
import { HistoricalSimilarityPanel } from "@/components/similarity/historical-similarity-panel";
import { RiskPanel } from "@/components/risk/risk-panel";
import { AlertCenter } from "@/components/alerts/alert-center";
import { Panel } from "@/components/layout/panel";
import { StateBadge } from "@/components/market/structure-badge";
import type { Timeframe } from "@/lib/types";

const TIMEFRAMES: Timeframe[] = ["H4", "H1", "M15", "M5"];

export default function SetupsPage() {
  const { snapshot } = useMarket();
  const structure = snapshot?.structure ?? {};

  return (
    <div className="p-4 flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-foreground tracking-tight">Setups</h1>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 flex flex-col gap-4">
          <SetupPanel setup={snapshot?.setup ?? null} />
          <AplusPanel />
          <HistoricalSimilarityPanel />

          <Panel title="Multi-Timeframe Context">
            <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-border">
              {TIMEFRAMES.map((tf) => {
                const s = structure[tf];
                return (
                  <div key={tf} className="px-3 first:pl-0 last:pr-0">
                    <p className="text-xs text-muted-foreground mb-1">{tf}</p>
                    {s ? <StateBadge state={s.state} /> : <span className="text-xs text-muted-foreground">—</span>}
                    {s?.reason && <p className="text-xs text-muted-foreground mt-2 leading-snug">{s.reason}</p>}
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>

        <div className="flex flex-col gap-4">
          <RiskPanel risk={snapshot?.risk ?? null} />
          <AlertCenter />
        </div>
      </div>
    </div>
  );
}
