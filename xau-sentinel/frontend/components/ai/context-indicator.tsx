import { cn } from "@/lib/utils";
import type { AnswerCategory, ContextSource } from "@/lib/types";

const CATEGORY_LABEL: Record<AnswerCategory, string> = {
  FACT: "Fact",
  CALCULATION: "Calculation",
  INTERPRETATION: "Interpretation",
  UNKNOWN: "Unknown / insufficient data",
};

/** Renders exactly what ai/assistant.py reports as context_used/sources —
 * never anything inferred from the answer text itself, so the user can
 * always see what an answer was (and wasn't) grounded in. */
export function ContextIndicator({ sources, category }: { sources: ContextSource[]; category: AnswerCategory }) {
  if (sources.length === 0) {
    return <p className="text-[11px] text-muted-foreground">No context was available for this answer.</p>;
  }

  return (
    <div className="text-[11px] text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1">
      <span className="uppercase tracking-wide shrink-0">Context used:</span>
      {sources.map((s) => (
        <span
          key={s.label}
          title={s.detail ?? undefined}
          className={cn("flex items-center gap-1", s.available ? "text-foreground" : "text-muted-foreground/60 line-through")}
        >
          {s.available ? "✓" : "✕"} {s.label}
        </span>
      ))}
      <span className="ml-auto shrink-0 rounded px-1.5 py-0.5 border border-border">
        {CATEGORY_LABEL[category]}
      </span>
    </div>
  );
}
