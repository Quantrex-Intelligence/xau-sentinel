import { Panel } from "@/components/layout/panel";
import { StateBadge } from "@/components/market/structure-badge";
import type { Structure, Timeframe } from "@/lib/types";

const TIMEFRAMES: Timeframe[] = ["H4", "H1", "M15", "M5"];

/** One row, one cell per timeframe. The reason for each state is in the
 * cell's tooltip, so the card itself stays minimal. */
export function StructurePanel({ structure }: { structure: Partial<Record<Timeframe, Structure>> }) {
  return (
    <Panel title="Market Structure">
      <div className="grid grid-cols-4 divide-x divide-border">
        {TIMEFRAMES.map((tf) => {
          const s = structure[tf];
          return (
            <div key={tf} className="flex flex-col items-center gap-1.5 px-2" title={s?.reason}>
              <span className="text-xs text-muted-foreground">{tf}</span>
              {s ? <StateBadge state={s.state} /> : <span className="text-xs text-muted-foreground">—</span>}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
