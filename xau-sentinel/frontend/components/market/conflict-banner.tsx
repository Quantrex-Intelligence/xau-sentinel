"use client";

import { Badge } from "@/components/ui/badge";
import type { ConflictView } from "@/lib/market-conflict";

/** Shown only when Market Analysis V2 and Entry Model V2 genuinely disagree (see
 * lib/market-conflict.ts::detectConflict). Renders nothing when there is no conflict -- this never
 * forces agreement and never fabricates reassurance when the two engines simply haven't resolved
 * yet. */
export function ConflictBanner({ conflict }: { conflict: ConflictView | null }) {
  if (!conflict) return null;
  return (
    <div
      role="alert"
      aria-label="Market context and Entry Model disagree"
      className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 flex flex-col gap-1 text-xs"
    >
      <div className="flex items-center gap-2">
        <Badge variant="warning">Disagreement</Badge>
        <span className="font-semibold text-foreground">Market Analysis and Entry Model disagree</span>
      </div>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4">
        <div>
          <dt className="inline text-muted-foreground">Market context: </dt>
          <dd className="inline text-foreground font-semibold">{conflict.marketContext}</dd>
        </div>
        <div>
          <dt className="inline text-muted-foreground">Entry Model: </dt>
          <dd className="inline text-foreground font-semibold">{conflict.entryModel}</dd>
        </div>
      </dl>
      <p>
        <span className="text-muted-foreground">Reason: </span>
        <span className="text-foreground">{conflict.reason}</span>
      </p>
    </div>
  );
}
