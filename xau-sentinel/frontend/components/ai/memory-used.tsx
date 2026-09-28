import { BrainCircuit } from "lucide-react";
import type { MemoryUsage } from "@/lib/types";

/** Renders exactly what ai/assistant.py reports as memory_used (Stage 7) —
 * never anything inferred from the answer text. Distinct from
 * KnowledgeSources (project documentation) and ToolsUsed (live tool
 * lookups): this is the user's own confirmed preferences/lessons/patterns —
 * contextual, never authoritative. Only rendered when non-empty. */
export function MemoryUsed({ memories }: { memories: MemoryUsage[] }) {
  if (memories.length === 0) return null;

  return (
    <div className="text-[11px] text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 mt-1">
      <span className="uppercase tracking-wide shrink-0">Memory referenced:</span>
      {memories.map((m) => (
        <span
          key={m.id}
          title={`${m.excerpt} (similarity ${m.similarity.toFixed(2)}, updated ${m.updated_at})`}
          className="flex items-center gap-1 text-foreground"
        >
          <BrainCircuit className="size-3 shrink-0" />
          {m.category}
        </span>
      ))}
    </div>
  );
}
