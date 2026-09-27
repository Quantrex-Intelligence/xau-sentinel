import { Panel } from "@/components/layout/panel";
import { StateBadge } from "@/components/market/structure-badge";
import type { Structure, Timeframe } from "@/lib/types";

const TIMEFRAMES: Timeframe[] = ["H4", "H1", "M15", "M5"];

export function StructurePanel({ structure }: { structure: Partial<Record<Timeframe, Structure>> }) {
  return (
    <Panel title="Market Structure">
      <div className="space-y-1">
        {TIMEFRAMES.map((tf) => {
          const s = structure[tf];
          return (
            <div key={tf} className="flex items-center justify-between py-1.5 border-b border-border last:border-0">
              <span className="text-sm text-muted-foreground w-10">{tf}</span>
              {s ? <StateBadge state={s.state} /> : <span className="text-xs text-muted-foreground">—</span>}
            </div>
          );
        })}
      </div>
      {structure.M5?.reason && (
        <p className="mt-3 text-xs text-muted-foreground">{structure.M5.reason}</p>
      )}
    </Panel>
  );
}
