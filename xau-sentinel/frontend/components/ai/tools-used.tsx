import { Wrench, CircleSlash } from "lucide-react";
import type { ToolUsage } from "@/lib/types";

/** Renders exactly what ai/assistant.py reports as tools_used (Stage 6) —
 * never anything inferred from the answer text. Distinct from
 * KnowledgeSources: these are live, read-only data lookups the model made
 * mid-turn, not reference documentation. Only rendered when non-empty — a
 * turn answered without any tool call shows nothing here. */
export function ToolsUsed({ tools }: { tools: ToolUsage[] }) {
  if (tools.length === 0) return null;

  return (
    <div className="text-[11px] text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 mt-1">
      <span className="uppercase tracking-wide shrink-0">Tools used:</span>
      {tools.map((t, i) => (
        <span
          key={`${t.name}-${i}`}
          title={t.data_available ? `Data available (as of ${t.timestamp ?? "unknown time"})` : "No data available"}
          className="flex items-center gap-1 text-foreground"
        >
          {t.data_available ? (
            <Wrench className="size-3 shrink-0" />
          ) : (
            <CircleSlash className="size-3 shrink-0 text-muted-foreground" />
          )}
          {t.label}
        </span>
      ))}
    </div>
  );
}
