import { Disclosure } from "@/components/layout/disclosure";
import { formatPrice } from "@/lib/format";
import type { Liquidity } from "@/lib/types";

export function LiquidityPanel({ liquidity }: { liquidity: Liquidity }) {
  const { sweeps, equal_levels } = liquidity;
  const total = sweeps.length + equal_levels.length;

  return (
    <Disclosure title="Liquidity" summary={total ? `${total} events` : "none yet"}>
      {sweeps.length > 0 && (
        <div className="mb-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">Recent sweeps</p>
          {sweeps.slice(-4).reverse().map((s, i) => (
            <div key={`s${i}`} className="flex items-center justify-between text-sm py-1">
              <span className="text-foreground">{s.label}</span>
              <span className="font-mono text-xs text-muted-foreground">{formatPrice(s.level_price)}</span>
            </div>
          ))}
        </div>
      )}
      {equal_levels.length > 0 && (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">Equal highs / lows</p>
          {equal_levels.slice(-4).reverse().map((e, i) => (
            <div key={`e${i}`} className="flex items-center justify-between text-sm py-1">
              <span className="text-foreground">{e.label}</span>
              <span className="font-mono text-xs text-muted-foreground">{formatPrice(e.level_price)}</span>
            </div>
          ))}
        </div>
      )}
    </Disclosure>
  );
}
