import { cn } from "@/lib/utils";
import { formatPrice } from "@/lib/format";

/** A used/remaining bar for a loss limit — visually obvious as it
 * approaches the floor, per the spec's "make it visually obvious when
 * approaching a limit." */
export function LimitBar({
  title,
  floor,
  remaining,
  usedPct,
}: {
  title: string;
  floor: number;
  remaining: number;
  usedPct: number;
}) {
  const clamped = Math.min(100, Math.max(0, usedPct));
  const tone = usedPct >= 100 ? "bg-bearish" : usedPct >= 80 ? "bg-bearish" : usedPct >= 50 ? "bg-warning" : "bg-bullish";

  return (
    <div>
      <div className="flex items-center justify-between text-sm mb-1">
        <span className="text-muted-foreground">{title}</span>
        <span className="font-mono font-medium">{usedPct.toFixed(0)}% used</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", tone)} style={{ width: `${clamped}%` }} />
      </div>
      <div className="flex items-center justify-between text-xs text-muted-foreground mt-1 font-mono">
        <span>Floor {formatPrice(floor)}</span>
        <span className={remaining <= 0 ? "text-bearish font-semibold" : ""}>
          {formatPrice(remaining)} remaining
        </span>
      </div>
    </div>
  );
}
