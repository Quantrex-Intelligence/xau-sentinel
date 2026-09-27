import { Panel } from "@/components/layout/panel";
import { formatPrice } from "@/lib/format";
import type { Liquidity } from "@/lib/types";

export function LiquidityPanel({ liquidity }: { liquidity: Liquidity }) {
  const { sweeps, equal_levels } = liquidity;
  const hasAny = sweeps.length > 0 || equal_levels.length > 0;

  return (
    <Panel title="Liquidity">
      {!hasAny && <span className="text-xs text-muted-foreground">No liquidity events yet.</span>}

      {sweeps.length > 0 && (
        <div className="mb-3">
          <p className="text-[11px] font-semibold text-muted-foreground mb-1">RECENT SWEEPS</p>
          {sweeps.slice(-4).reverse().map((s, i) => (
            <div key={i} className="flex items-center justify-between text-sm py-1">
              <span className="text-foreground">{s.label}</span>
              <span className="font-mono text-xs text-muted-foreground">{formatPrice(s.level_price)}</span>
            </div>
          ))}
        </div>
      )}

      {equal_levels.length > 0 && (
        <div>
          <p className="text-[11px] font-semibold text-muted-foreground mb-1">EQUAL HIGHS / LOWS</p>
          {equal_levels.slice(-4).reverse().map((e, i) => (
            <div key={i} className="flex items-center justify-between text-sm py-1">
              <span className="text-foreground">{e.label}</span>
              <span className="font-mono text-xs text-muted-foreground">{formatPrice(e.level_price)}</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
