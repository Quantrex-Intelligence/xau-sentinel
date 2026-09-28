"use client";

import type { ReactNode } from "react";
import { Panel } from "@/components/layout/panel";
import { usePolling } from "@/lib/use-polling";
import { api } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ContextualAnalysis, StrategyCriterion, StrategyCriterionStatus, StrategyRating } from "@/lib/types";
import { Check, X, HelpCircle, Sparkles } from "lucide-react";

const RATING_STYLES: Record<StrategyRating, { text: string; bg: string; dot: string }> = {
  "A+": { text: "text-bullish", bg: "bg-bullish/10 border-bullish/30", dot: "bg-bullish" },
  DEVELOPING: { text: "text-warning", bg: "bg-warning/10 border-warning/30", dot: "bg-warning" },
  INVALID: { text: "text-bearish", bg: "bg-bearish/10 border-bearish/30", dot: "bg-bearish" },
};

const STATUS_ICON: Record<StrategyCriterionStatus, ReactNode> = {
  passed: <Check className="size-3" />,
  failed: <X className="size-3" />,
  unknown: <HelpCircle className="size-3" />,
};

const STATUS_STYLE: Record<StrategyCriterionStatus, string> = {
  passed: "bg-bullish/20 text-bullish",
  failed: "bg-bearish/20 text-bearish",
  unknown: "bg-muted text-muted-foreground",
};

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, { hour12: false });
  } catch {
    return iso;
  }
}

function CriterionRow({ criterion }: { criterion: StrategyCriterion }) {
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-border last:border-0">
      <span className={cn("mt-0.5 flex items-center justify-center size-4 rounded-full shrink-0",
                           STATUS_STYLE[criterion.status])}>
        {STATUS_ICON[criterion.status]}
      </span>
      <div className="min-w-0">
        <p className="text-sm text-foreground">{criterion.name}</p>
        <p className="text-[11px] text-muted-foreground leading-snug">{criterion.evidence}</p>
      </div>
    </div>
  );
}

/** Stage 10: one deterministic section — plain text Sentinel already knows,
 * never LLM output. Distinct visual treatment from <InterpretationSection>
 * below, per the "what does Sentinel know vs. what does the AI think"
 * distinction the spec asks for. */
function AnalysisSection({ label, text }: { label: string; text: string }) {
  return (
    <div className="mb-2">
      <p className="text-[11px] font-semibold text-muted-foreground uppercase mb-1">{label}</p>
      <p className="text-xs text-foreground leading-snug">{text}</p>
    </div>
  );
}

function InterpretationSection({ analysis }: { analysis: ContextualAnalysis }) {
  return (
    <div className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 mb-3">
      <p className="text-[11px] font-semibold text-primary uppercase mb-1 flex items-center gap-1">
        <Sparkles className="size-3" /> AI Interpretation
      </p>
      <p className="text-xs text-foreground whitespace-pre-wrap">{analysis.interpretation}</p>
      {analysis.uncertainties.length > 0 && (
        <p className="text-[11px] text-muted-foreground mt-1">
          Uncertainties: {analysis.uncertainties.join("; ")}
        </p>
      )}
    </div>
  );
}

/** Stage 10: the contextual-analysis block — Technical/Strategy/Market
 * Intelligence/Historical/Risk are all deterministic text built from the
 * evidence Sentinel already gathered (see ai/strategy/evidence.py); only
 * "AI Interpretation" above is LLM-authored, and it's the only section
 * styled distinctly. Market Intelligence renders only when relevant —
 * never padded with an empty macro/events/news block. */
function ContextualAnalysisBlock({ analysis }: { analysis: ContextualAnalysis }) {
  return (
    <div className="mb-3 pt-3 border-t border-border">
      <AnalysisSection label="Technical" text={analysis.technical_summary} />
      <AnalysisSection label="Strategy" text={analysis.strategy_summary} />
      {analysis.market_intelligence.relevant && (
        <AnalysisSection
          label="Market Intelligence"
          text={[
            analysis.market_intelligence.macro,
            analysis.market_intelligence.events,
            analysis.market_intelligence.news,
            analysis.market_intelligence.cross_asset,
          ].filter(Boolean).join(" ")}
        />
      )}
      <AnalysisSection label="Historical Context" text={analysis.historical_context} />
      <AnalysisSection label="Risk" text={analysis.risk_context} />
      <InterpretationSection analysis={analysis} />
    </div>
  );
}

/** Stage 4: the A+ strategy evaluation panel. Deliberately separate from
 * <SetupPanel> (the frozen Stage 1 panel just above it on the Setups page)
 * — this shows the STRICTER, user-specified A+ criteria layered on top of
 * Stage 1's own setup state, never replacing it. */
export function AplusPanel() {
  const { data: result, error } = usePolling(() => api.strategyAPlus(), 20000);

  if (error) {
    return (
      <Panel title="A+ Strategy Evaluation">
        <p className="text-xs text-muted-foreground">Evaluation unavailable — {error.message}</p>
      </Panel>
    );
  }

  if (!result) {
    return (
      <Panel title="A+ Strategy Evaluation">
        <span className="text-xs text-muted-foreground">Loading…</span>
      </Panel>
    );
  }

  const style = RATING_STYLES[result.rating];

  return (
    <Panel title="A+ Strategy Evaluation">
      <div className={cn("rounded-md border px-3 py-2 mb-3 flex items-center gap-2", style.bg)}>
        <span className={cn("size-2 rounded-full shrink-0", style.dot)} />
        <span className={cn("text-lg font-bold tracking-wide", style.text)}>
          {result.direction ? `${result.direction} — ` : ""}
          {result.rating}
        </span>
      </div>

      {result.invalidation && (
        <p className="text-xs text-bearish mb-3">{result.invalidation}</p>
      )}

      {result.criteria.length > 0 && (
        <div className="mb-3">
          {result.criteria.map((c) => (
            <CriterionRow key={c.name} criterion={c} />
          ))}
        </div>
      )}

      {result.missing_conditions.length > 0 && (
        <p className="text-[11px] text-muted-foreground mb-3">
          Missing: {result.missing_conditions.join(", ")}
        </p>
      )}

      {result.entry !== null && (
        <div className="grid grid-cols-2 gap-2 pb-3 mb-3 border-b border-border text-sm">
          <PlanField label="Entry" value={formatPrice(result.entry)} />
          <PlanField label="Stop Loss" value={formatPrice(result.stop_loss)} />
          <PlanField label="Target" value={formatPrice(result.target)} />
          <PlanField label="R:R" value={result.rr !== null ? `1:${result.rr}` : "—"} />
        </div>
      )}

      <div className="mb-3">
        <p className="text-[11px] font-semibold text-muted-foreground uppercase mb-1">FundedNext Risk</p>
        {result.fundednext.data_available ? (
          <p className="text-xs text-foreground">
            {result.fundednext.safety_level} · daily loss used {result.fundednext.daily_loss_used_pct}% (limit for A+: {result.fundednext.max_daily_loss_used_pct_allowed}%)
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">{result.fundednext.reason ?? "Unavailable"}</p>
        )}
      </div>

      {result.context_evidence.length > 0 && (
        <div className="mb-3">
          <p className="text-[11px] font-semibold text-muted-foreground uppercase mb-1">Context</p>
          {result.context_evidence.map((e, i) => (
            <p key={i} className="text-[11px] text-muted-foreground leading-snug">{e}</p>
          ))}
        </div>
      )}

      {(result.llm_explanation || result.llm_error) && (
        <div className="mb-3">
          <p className="text-[11px] font-semibold text-muted-foreground uppercase mb-1">AI Explanation</p>
          {result.llm_explanation ? (
            <p className="text-xs text-foreground whitespace-pre-wrap">{result.llm_explanation}</p>
          ) : (
            <p className="text-xs text-muted-foreground">{result.llm_error}</p>
          )}
        </div>
      )}

      {result.contextual_analysis && <ContextualAnalysisBlock analysis={result.contextual_analysis} />}

      <p className="text-[10px] text-muted-foreground">Evaluated {formatTimestamp(result.evaluated_at)}</p>
    </Panel>
  );
}

function PlanField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="font-mono font-medium text-foreground">{value}</p>
    </div>
  );
}
