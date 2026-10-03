"use client";

import { Disclosure } from "@/components/layout/disclosure";
import { cn } from "@/lib/utils";
import type { Setup } from "@/lib/types";
import { Check } from "lucide-react";

/** Checklist only. The setup state and plan are in the summary panel; this
 * collapses the step list to a count so it doesn't dominate the page. */
export function SetupPanel({ setup }: { setup: Setup | null }) {
  if (!setup) return <Disclosure title="Setup checklist" summary="no data" />;

  const entries = Object.entries(setup.checklist);
  const done = entries.filter(([, value]) => value === true).length;

  return (
    <Disclosure title="Setup checklist" summary={`${done}/${entries.length}`}>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        {entries.map(([step, value]) => (
          <div key={step} className="flex items-center gap-2 text-sm">
            <span
              className={cn(
                "flex items-center justify-center size-4 rounded-full shrink-0",
                value === true ? "bg-bullish/20 text-bullish" : "border border-border"
              )}
            >
              {value === true && <Check className="size-3" />}
            </span>
            <span className={value === true ? "text-foreground" : "text-muted-foreground"}>{step}</span>
          </div>
        ))}
      </div>
    </Disclosure>
  );
}
