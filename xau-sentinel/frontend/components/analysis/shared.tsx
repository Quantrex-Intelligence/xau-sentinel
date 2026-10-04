"use client";

import { Badge } from "@/components/ui/badge";

/** "HH:MM UTC" from an ISO timestamp. Times from the API are always UTC. */
export function utcClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")} UTC`;
}

/** Makes the kind of statement explicit: observed fact, interpreted relationship, or conditional scenario. */
export function KindTag({ kind }: { kind: "observed" | "interpreted" | "conditional" }) {
  const map = {
    observed: { label: "Observed", variant: "outline" as const, help: "Measured directly from closed candles." },
    interpreted: { label: "Interpreted", variant: "secondary" as const, help: "Derived from the observed facts." },
    conditional: { label: "Conditional", variant: "warning" as const, help: "What would need to happen. Not a forecast." },
  }[kind];
  return (
    <Badge variant={map.variant} title={map.help} className="text-[10px] uppercase tracking-wide">
      {map.label}
    </Badge>
  );
}
