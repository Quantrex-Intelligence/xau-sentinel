"use client";

import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/layout/panel";
import type { AnalysisV2Scenario } from "@/lib/types";
import { KindTag } from "@/components/analysis/shared";

const SCENARIO_TITLE: Record<string, string> = {
  CONTINUATION: "Continuation",
  REVERSAL: "Reversal",
  RANGE: "Range",
};

function ScenarioCard({ scenario }: { scenario: AnalysisV2Scenario }) {
  const directionLabel = scenario.direction ? `${scenario.direction} case` : "two-sided";
  return (
    <article aria-label={`${SCENARIO_TITLE[scenario.name] ?? scenario.name} scenario`} className="rounded-lg border border-border px-4 py-3 flex flex-col gap-3">
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">{SCENARIO_TITLE[scenario.name] ?? scenario.name}</h3>
        <Badge variant="outline" className="text-[10px]">{directionLabel}</Badge>
      </header>
      <p className="text-sm text-foreground leading-relaxed">{scenario.condition}</p>

      {scenario.supporting_conditions.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">Evidence that currently points this way</p>
          <ul className="text-xs text-muted-foreground list-disc pl-4">
            {scenario.supporting_conditions.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="rounded-md bg-muted/40 px-3 py-2">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">Confirmation requires</p>
          <ul className="text-xs text-foreground list-disc pl-4">
            {scenario.confirmation_requirements.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-md bg-muted/40 px-3 py-2">
          <p className="text-[10px] uppercase tracking-wide text-bearish mb-1">Invalidated if</p>
          <ul className="text-xs text-foreground list-disc pl-4">
            {scenario.invalidation_conditions.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      </div>

      {(scenario.key_area_refs.length > 0 || scenario.event_refs.length > 0) && (
        <div className="text-[11px] text-muted-foreground flex flex-col gap-1">
          {scenario.key_area_refs.length > 0 && <p>Areas: {scenario.key_area_refs.join(" · ")}</p>}
          {scenario.event_refs.length > 0 && <p>Events: {scenario.event_refs.join(" · ")}</p>}
        </div>
      )}
      <p className="text-[10px] text-muted-foreground italic">{scenario.disclaimer}</p>
    </article>
  );
}

export function AnalysisScenarios({ scenarios }: { scenarios: AnalysisV2Scenario[] }) {
  return (
    <Panel title="Conditional scenarios" action={<KindTag kind="conditional" />}>
      {scenarios.length === 0 ? (
        <p className="text-sm text-muted-foreground">No scenario can be framed until the structure levels are available.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3">
          {scenarios.map((s) => (
            <ScenarioCard key={s.name} scenario={s} />
          ))}
        </div>
      )}
    </Panel>
  );
}
