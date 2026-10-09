"use client";

import { Panel } from "@/components/layout/panel";
import { Disclosure } from "@/components/layout/disclosure";
import { Badge } from "@/components/ui/badge";
import { Sparkles } from "lucide-react";
import type { EntryModelJudgeResult } from "@/lib/types";

const VERDICT_TONE: Record<string, "bullish" | "warning" | "bearish" | "secondary"> = {
  SUPPORTED: "bullish", CAUTION: "warning", REJECTED: "bearish", INSUFFICIENT_EVIDENCE: "secondary",
};

const QUALITY_LABEL: Record<string, string> = {
  HIGH: "High", MODERATE: "Moderate", LOW: "Low", UNASSESSABLE: "Unassessable",
};

function ListBlock({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-0.5">{label}</p>
      <ul className="flex flex-col gap-0.5">
        {items.map((item, i) => (
          <li key={i} className="text-xs text-foreground leading-snug">• {item}</li>
        ))}
      </ul>
    </div>
  );
}

/** The one badge that is never conditional on anything -- it renders whenever this card renders,
 * in every state (disabled, not-eligible, failed, OK), so "this is an LLM, not the deterministic
 * system" can never be missed. */
function ShadowModeBadge() {
  return (
    <Badge variant="outline" className="border-primary/40 text-primary">
      <Sparkles className="size-3" /> SHADOW MODE
    </Badge>
  );
}

export function EntryJudgeCard({ result }: { result: EntryModelJudgeResult | null }) {
  if (!result) {
    return (
      <Panel title="LLM setup judge" density="compact" action={<ShadowModeBadge />}>
        <p className="text-xs text-muted-foreground">Waiting for the first evaluation.</p>
      </Panel>
    );
  }

  if (!result.enabled) {
    return (
      <Panel title="LLM setup judge" density="compact" action={<ShadowModeBadge />}>
        <p className="text-xs text-muted-foreground">Disabled (ENTRY_JUDGE_ENABLED=false).</p>
      </Panel>
    );
  }

  if (!result.eligible) {
    return (
      <Panel title="LLM setup judge" density="compact" action={<ShadowModeBadge />}>
        <p className="text-xs text-muted-foreground">
          {result.not_eligible_reason ?? "No eligible candidate right now."}
        </p>
      </Panel>
    );
  }

  if (result.status === "FAILED") {
    return (
      <Panel title="LLM setup judge" density="compact" action={<ShadowModeBadge />}>
        <p className="text-xs text-muted-foreground">
          Evaluation failed ({result.error_category ?? "unknown"}). The deterministic Entry Model is
          unaffected.
        </p>
      </Panel>
    );
  }

  return (
    <Panel
      title="LLM setup judge"
      density="compact"
      action={
        <div className="flex items-center gap-2">
          <ShadowModeBadge />
          {result.verdict && <Badge variant={VERDICT_TONE[result.verdict]}>{result.verdict}</Badge>}
        </div>
      }
    >
      <div className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-[11px] font-semibold text-primary uppercase tracking-wide flex items-center gap-1">
            <Sparkles className="size-3" /> Independent AI review — not the Entry Model&apos;s own state
          </p>
          {result.quality && (
            <p className="text-xs text-muted-foreground">
              Evidence quality: <span className="text-foreground">{QUALITY_LABEL[result.quality] ?? result.quality}</span>
            </p>
          )}
        </div>

        {result.reasoning_summary && (
          <p className="text-sm text-foreground whitespace-pre-wrap">{result.reasoning_summary}</p>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <ListBlock label="Supporting evidence" items={result.supporting_evidence} />
          <ListBlock label="Contradictions" items={result.contradictions} />
          <ListBlock label="Missing confirmations" items={result.missing_confirmations} />
          <ListBlock label="Risk flags" items={result.risk_flags} />
        </div>

        <Disclosure title="Detail" summary="invalidation conditions, evidence references, provenance">
          <div className="flex flex-col gap-2 text-xs">
            <ListBlock label="Invalidation conditions" items={result.invalidation_conditions} />
            <ListBlock label="Evidence references" items={result.evidence_references} />
            <p className="text-[10px] text-muted-foreground">
              {result.llm_provider ?? "—"} / {result.llm_model ?? "—"} · prompt {result.prompt_version ?? "—"} ·
              {" "}{result.is_reassessment ? "reassessment" : "first evaluation"} of this candidate ·
              {" "}evaluated {result.evaluated_at ?? "—"}
            </p>
          </div>
        </Disclosure>

        <p className="text-[10px] text-muted-foreground">{result.disclaimer}</p>
      </div>
    </Panel>
  );
}
