"use client";

import { useState } from "react";
import { Panel } from "@/components/layout/panel";
import { NewTradeForm } from "@/components/journal/new-trade-form";
import { TradeTable } from "@/components/journal/trade-table";
import { TradeDetailSheet } from "@/components/journal/trade-detail-sheet";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";
import type { Trade } from "@/lib/types";

export default function JournalPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [selected, setSelected] = useState<Trade | null>(null);
  const { data: trades } = usePolling(() => api.trades(), 5000, [refreshKey]);

  function refetch() {
    setRefreshKey((k) => k + 1);
  }

  return (
    <div className="p-4 flex flex-col gap-4">
      <NewTradeForm onCreated={refetch} />

      <Panel title="Trades">
        <TradeTable trades={trades ?? []} onSelect={setSelected} />
      </Panel>

      <TradeDetailSheet
        trade={selected}
        onOpenChange={(open) => !open && setSelected(null)}
        onClosed={refetch}
      />
    </div>
  );
}
