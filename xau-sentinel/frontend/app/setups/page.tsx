"use client";

import { useMarket } from "@/lib/market-context";
import { SummaryPanel } from "@/components/market/summary-strip";
import { StructurePanel } from "@/components/market/structure-panel";
import { SetupPanel } from "@/components/setup/setup-panel";
import { AplusPanel } from "@/components/strategy/a-plus-panel";
import { HistoricalSimilarityPanel } from "@/components/similarity/historical-similarity-panel";
import { RiskPanel } from "@/components/risk/risk-panel";
import { AlertCenter } from "@/components/alerts/alert-center";

export default function SetupsPage() {
  const { snapshot } = useMarket();

  return (
    <div className="p-4 flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-foreground tracking-tight">Setups</h1>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 flex flex-col gap-4">
          <SummaryPanel
            structure={snapshot?.structure ?? {}}
            regime={snapshot?.regime ?? null}
            setup={snapshot?.setup ?? null}
          />
          <StructurePanel structure={snapshot?.structure ?? {}} />
          <SetupPanel setup={snapshot?.setup ?? null} />
          <AplusPanel />
          <HistoricalSimilarityPanel />
        </div>

        <div className="flex flex-col gap-4">
          <RiskPanel risk={snapshot?.risk ?? null} />
          <AlertCenter />
        </div>
      </div>
    </div>
  );
}
