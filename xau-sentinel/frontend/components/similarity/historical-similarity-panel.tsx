"use client";

import { Panel } from "@/components/layout/panel";
import { usePolling } from "@/lib/use-polling";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatR } from "@/lib/format";
import type { SimilarSetup, SimilarityOutcome } from "@/lib/types";

const OUTCOME_STYLE: Record<string, string> = {
  WIN: "bg-bullish/20 text-bullish",
  LOSS: "bg-bearish/20 text-bearish",
  BE: "bg-muted text-foreground",
};

function outcomeLabel(outcome: SimilarityOutcome): string {
  if (outcome.status === "OPEN") return "OPEN";
  return outcome.result ?? "UNKNOWN";
}

function OutcomeBadge({ outcome }: { outcome: SimilarityOutcome }) {
  const label = outcomeLabel(outcome);
  return (
    <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase",
                         OUTCOME_STYLE[label] ?? "bg-muted text-muted-foreground")}>
      {label}
    </span>
  );
}

function FeatureChips({ features, positive }: { features: string[]; positive: boolean }) {
  if (features.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {features.map((f) => (
        <span
          key={f}
          className={cn(
            "text-[10px] px-1.5 py-0.5 rounded",
            positive ? "bg-bullish/10 text-bullish" : "bg-muted text-muted-foreground"
          )}
        >
          {f.replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}

function MatchRow({ match }: { match: SimilarSetup }) {
  return (
    <div className="border-b border-border last:border-0 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm text-foreground">
          Trade #{match.trade_id} — <span className="font-mono">{(match.similarity * 100).toFixed(0)}%</span>{" "}
          <span className="text-muted-foreground text-xs">feature similarity</span>
        </span>
        <div className="flex items-center gap-2 shrink-0">
          <OutcomeBadge outcome={match.outcome} />
          {match.outcome.r_multiple !== null && (
            <span className="text-xs font-mono text-muted-foreground">{formatR(match.outcome.r_multiple)}</span>
          )}
        </div>
      </div>
      <FeatureChips features={match.matched_features} positive />
      <FeatureChips features={match.different_features} positive={false} />
    </div>
  );
}

/** Stage 8: descriptive historical setup similarity, never a probability
 * or confidence-of-success claim — see ai/similarity/scoring.py. Sits
 * alongside (never inside) the deterministic A+ panel; nothing here can
 * change that evaluation. */
export function HistoricalSimilarityPanel() {
  const { data: result, error } = usePolling(() => api.similarityCurrent(), 20000);

  if (error) {
    return (
      <Panel title="Historical Similarity">
        <p className="text-xs text-muted-foreground">Unavailable — {error.message}</p>
      </Panel>
    );
  }

  if (!result) {
    return (
      <Panel title="Historical Similarity">
        <span className="text-xs text-muted-foreground">Loading…</span>
      </Panel>
    );
  }

  return (
    <Panel title="Historical Similarity">
      <p className="text-[11px] text-muted-foreground mb-2">
        Feature overlap against past journal trades — descriptive only, never a prediction of this
        trade&apos;s outcome.
      </p>
      <p className="text-[11px] text-muted-foreground mb-2">
        {result.matches.length} match{result.matches.length === 1 ? "" : "es"} · {result.considered_count} trade
        {result.considered_count === 1 ? "" : "s"} considered
        {result.excluded_count > 0 ? ` · ${result.excluded_count} excluded (insufficient entry data)` : ""}
      </p>

      {result.matches.length === 0 ? (
        <p className="text-xs text-muted-foreground">No sufficiently similar historical setups found.</p>
      ) : (
        <div>
          {result.matches.map((m) => (
            <MatchRow key={m.trade_id} match={m} />
          ))}
        </div>
      )}
    </Panel>
  );
}
