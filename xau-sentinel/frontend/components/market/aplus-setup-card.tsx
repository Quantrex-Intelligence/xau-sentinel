"use client";

import { Panel } from "@/components/layout/panel";
import { Badge } from "@/components/ui/badge";
import { formatPrice } from "@/lib/format";
import { aplusLabel, checkState, type CheckState } from "@/lib/market-view";
import type { StrategyEvaluation } from "@/lib/types";

const MARK: Record<CheckState, { glyph: string; cls: string; text: string }> = {
  met: { glyph: "✓", cls: "text-bullish", text: "met" },
  waiting: { glyph: "○", cls: "text-muted-foreground", text: "waiting" },
  invalidated: { glyph: "✕", cls: "text-bearish", text: "invalidated" },
  unknown: { glyph: "?", cls: "text-muted-foreground", text: "unknown" },
};

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-muted/40 px-2.5 py-1.5 min-w-0">
      <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="text-xs font-semibold font-mono tabular-nums text-foreground truncate">{value}</dd>
    </div>
  );
}

export function AplusSetupCard({ evaluation }: { evaluation: StrategyEvaluation | null }) {
  if (!evaluation) {
    return (
      <Panel title="A+ setup" density="compact">
        <p className="text-xs text-muted-foreground">Waiting for the first A+ evaluation.</p>
      </Panel>
    );
  }
  const state = aplusLabel(evaluation.rating);
  const badge = state === "Valid" ? "bullish" : state === "Invalid" ? "bearish" : "warning";
  const next = evaluation.criteria.find((c) => c.status !== "passed")?.name ?? evaluation.missing_conditions[0] ?? null;
  const fmt = (v: number | null) => (v === null ? "—" : formatPrice(v));
  return (
    <Panel
      title="A+ setup"
      density="compact"
      action={<Badge variant={badge}>{state}</Badge>}
    >
      <div className="flex flex-col gap-2.5">
        <p className="text-xs text-muted-foreground">
          Direction <span className="font-semibold text-foreground">{evaluation.direction ?? "none"}</span>
          {evaluation.direction === null && " · no candidate sweep in the window"}
        </p>
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1">
          {evaluation.criteria.map((c) => {
            const mark = MARK[checkState(c, evaluation.rating)];
            return (
              <li key={c.name} className="flex items-center gap-2 text-xs" title={c.evidence}>
                <span aria-hidden className={`w-3 text-center font-semibold ${mark.cls}`}>{mark.glyph}</span>
                <span className="text-foreground">{c.name}</span>
                <span className={`ml-auto text-[10px] ${mark.cls}`}>{mark.text}</span>
              </li>
            );
          })}
        </ul>
        <dl className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <Value label="Entry" value={fmt(evaluation.entry)} />
          <Value label="Stop" value={fmt(evaluation.stop_loss)} />
          <Value label="Target" value={fmt(evaluation.target)} />
          <Value label="R:R" value={evaluation.rr === null ? "—" : `1:${evaluation.rr.toFixed(2)}`} />
        </dl>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
          <p>
            <span className="text-muted-foreground">Next condition: </span>
            <span className="text-foreground">{next ?? "none"}</span>
          </p>
          <p>
            <span className="text-muted-foreground">Invalidated if: </span>
            <span className="text-foreground">{evaluation.invalidation ?? "no invalidation recorded"}</span>
          </p>
        </div>
      </div>
    </Panel>
  );
}
