import { BookOpen } from "lucide-react";
import type { KnowledgeSource } from "@/lib/types";

/** Renders exactly what ai/assistant.py reports as knowledge_used (Stage
 * 5) — never anything inferred from the answer text. Distinct from
 * ContextIndicator: these are reference documents cited for this turn, not
 * live deterministic facts, so they're labeled and styled separately. Only
 * rendered when non-empty — a turn with no relevant knowledge shows
 * nothing here, matching that RAG never forces a match. */
export function KnowledgeSources({ sources }: { sources: KnowledgeSource[] }) {
  if (sources.length === 0) return null;

  return (
    <div className="text-[11px] text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 mt-1">
      <span className="uppercase tracking-wide shrink-0">Knowledge referenced:</span>
      {sources.map((s, i) => (
        <span
          key={`${s.source}-${i}`}
          title={`${s.excerpt} (similarity ${s.similarity.toFixed(2)})`}
          className="flex items-center gap-1 text-foreground"
        >
          <BookOpen className="size-3 shrink-0" />
          {s.title} <span className="text-muted-foreground">v{s.version}</span>
        </span>
      ))}
    </div>
  );
}
