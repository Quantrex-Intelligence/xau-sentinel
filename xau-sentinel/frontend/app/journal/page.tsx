"use client";

import { useState } from "react";
import { Panel } from "@/components/layout/panel";
import { NewTradeForm } from "@/components/journal/new-trade-form";
import { TradeTable } from "@/components/journal/trade-table";
import { TradeDetailSheet } from "@/components/journal/trade-detail-sheet";
import { TradeReviewOverviewPanel } from "@/components/journal/trade-review-overview-panel";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";
import type { Trade } from "@/lib/types";

export default function JournalPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const { data: trades } = usePolling(() => api.trades(), 5000, [refreshKey]);

  function refetch() {
    setRefreshKey((k) => k + 1);
  }

  function handleSelect(trade: Trade) {
    setSelectedId(trade.id);
  }

  return (
    <div className="p-4 flex flex-col gap-4">
      <NewTradeForm onCreated={refetch} />

      <Panel title="Trades">
        <TradeTable trades={trades ?? []} onSelect={handleSelect} />
      </Panel>

      <TradeReviewOverviewPanel />

      <TradeDetailSheet
        tradeId={selectedId}
        onOpenChange={(open) => !open && setSelectedId(null)}
        onClosed={refetch}
      />
    </div>
  );
}
