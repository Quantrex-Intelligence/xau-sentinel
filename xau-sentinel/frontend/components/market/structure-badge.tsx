import { cn } from "@/lib/utils";
import type { StructureState } from "@/lib/types";

const STATE_STYLES: Record<string, string> = {
  BULLISH: "text-bullish bg-bullish/10",
  BEARISH: "text-bearish bg-bearish/10",
  RANGING: "text-muted-foreground bg-muted",
  PULLBACK: "text-warning bg-warning/10",
  "TRENDING UP": "text-bullish bg-bullish/10",
  "TRENDING DOWN": "text-bearish bg-bearish/10",
  BREAKOUT: "text-info bg-info/10",
  "HIGH VOLATILITY": "text-[#c678dd] bg-[#c678dd]/10",
  "LOW VOLATILITY": "text-muted-foreground bg-muted",
};

export function StateBadge({ state }: { state: StructureState | string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-2 py-0.5 text-xs font-bold tracking-wide",
        STATE_STYLES[state] ?? "text-muted-foreground bg-muted"
      )}
    >
      {state}
    </span>
  );
}
