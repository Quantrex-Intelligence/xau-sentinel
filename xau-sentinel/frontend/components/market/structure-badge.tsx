import { Badge, type badgeVariants } from "@/components/ui/badge";
import type { VariantProps } from "class-variance-authority";
import type { StructureState } from "@/lib/types";

type BadgeVariant = VariantProps<typeof badgeVariants>["variant"];

const STATE_VARIANT: Record<string, BadgeVariant> = {
  BULLISH: "bullish",
  "TRENDING UP": "bullish",
  BEARISH: "bearish",
  "TRENDING DOWN": "bearish",
  PULLBACK: "warning",
  BREAKOUT: "info",
  RANGING: "secondary",
  "LOW VOLATILITY": "secondary",
};

// Distinct from the other states on purpose (not "warning") -- high
// volatility isn't a bullish/bearish/pullback signal, it's a separate axis.
const HIGH_VOLATILITY_CLASS = "bg-[#c678dd]/10 text-[#c678dd]";

export function StateBadge({ state }: { state: StructureState | string }) {
  if (state === "HIGH VOLATILITY") {
    return (
      <Badge variant="outline" className={HIGH_VOLATILITY_CLASS}>
        {state}
      </Badge>
    );
  }
  return <Badge variant={STATE_VARIANT[state] ?? "secondary"}>{state}</Badge>;
}
