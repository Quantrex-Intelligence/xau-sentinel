"use client";

import { Panel } from "@/components/layout/panel";
import type { MarketStory } from "@/lib/market-view";

const ROWS: { key: keyof MarketStory; label: string }[] = [
  { key: "happening", label: "What is happening" },
  { key: "where", label: "Where is price" },
  { key: "area", label: "Important area" },
  { key: "justHappened", label: "What just happened" },
  { key: "waitingFor", label: "Waiting for" },
];

export function WhatMattersNow({ story }: { story: MarketStory }) {
  return (
    <Panel title="What matters now" density="compact">
      <dl className="flex flex-col divide-y divide-border">
        {ROWS.map(({ key, label }) => (
          <div key={key} className="grid grid-cols-[9rem_1fr] gap-2 py-1.5">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-xs text-foreground leading-snug">{story[key] ?? "—"}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-[10px] text-muted-foreground">
        Deterministic V2 narrative on closed candles. It describes the market and does not recommend an action.
      </p>
    </Panel>
  );
}
