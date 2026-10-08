"use client";

import { Panel } from "@/components/layout/panel";
import { Badge } from "@/components/ui/badge";
import type { ScenarioView } from "@/lib/market-view";

const TONE: Record<ScenarioView["key"], "bullish" | "bearish" | "secondary"> = {
  bullish: "bullish",
  bearish: "bearish",
  neutral: "secondary",
};

function Line({ label, text }: { label: string; text: string | null }) {
  return (
    <p className="text-xs leading-snug">
      <span className="text-muted-foreground">{label}: </span>
      <span className="text-foreground">{text ?? "—"}</span>
    </p>
  );
}

export function ScenariosCard({ scenarios }: { scenarios: ScenarioView[] }) {
  return (
    <Panel title="Scenarios" density="compact">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {scenarios.map((s) => (
          <article key={s.key} aria-label={`${s.title} scenario`} className="rounded-md border border-border px-3 py-2 flex flex-col gap-1.5">
            <header className="flex items-center gap-2">
              <Badge variant={TONE[s.key]}>{s.title}</Badge>
              <Badge variant={s.status === "Invalidated" ? "bearish" : s.status === "Active" ? "secondary" : "outline"}>
                {s.status}
              </Badge>
            </header>
            <Line label="Trigger" text={s.trigger} />
            <Line label="Means" text={s.meaning} />
            <Line label="Invalid if" text={s.invalidation} />
          </article>
        ))}
      </div>
    </Panel>
  );
}
