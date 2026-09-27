import { Panel } from "@/components/layout/panel";
import { StateBadge } from "@/components/market/structure-badge";
import type { Regime } from "@/lib/types";

export function RegimePanel({ regime }: { regime: Regime | null }) {
  return (
    <Panel title="Market Regime">
      {regime ? (
        <>
          <StateBadge state={regime.regime} />
          <p className="mt-3 text-xs text-muted-foreground leading-relaxed">{regime.reason}</p>
        </>
      ) : (
        <span className="text-xs text-muted-foreground">No data</span>
      )}
    </Panel>
  );
}
